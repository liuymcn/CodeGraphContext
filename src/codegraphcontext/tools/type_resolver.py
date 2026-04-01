"""
Type resolution utilities for CGC V5.6.

Extracted from graph_builder.py to reduce file size and improve modularity.
All functions take a DB session as first parameter — no class dependency.
"""
from codegraphcontext.utils.debug_log import debug_log, info_logger


# ─── Hierarchy traversal ───────────────────────────────────────────

def linear_ancestors(session, class_name, repo_prefix):
    """BFS ancestor chain — follows ALL parents (handles implements + extends)."""
    chain, visited, queue = [], set(), [class_name]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        chain.append(current)
        parents = session.run("""
            MATCH (c {name: $cls})-[:INHERITS]->(p)
            WHERE (c:Class OR c:Interface) AND c.path STARTS WITH $repo
            RETURN p.name AS name
        """, cls=current, repo=repo_prefix).data()
        for p in parents:
            if p['name'] not in visited:
                queue.append(p['name'])
    return chain


def compute_mro(session, class_name, repo_prefix):
    """C3 linearization for Python multiple inheritance."""
    results = session.run("""
        MATCH (c {name: $cls})-[:INHERITS]->(p)
        WHERE (c:Class OR c:Interface) AND c.path STARTS WITH $repo
        RETURN p.name AS name
    """, cls=class_name, repo=repo_prefix).data()
    parents = [r['name'] for r in results]
    if not parents:
        return [class_name]
    parent_mros = [compute_mro(session, p, repo_prefix) for p in parents]
    try:
        return [class_name] + _c3_merge([list(m) for m in parent_mros] + [list(parents)])
    except Exception:
        return [class_name] + parents


def _c3_merge(sequences):
    """C3 merge algorithm."""
    result = []
    seqs = [s for s in sequences if s]
    while seqs:
        for seq in seqs:
            head = seq[0]
            if all(head not in s[1:] for s in seqs):
                result.append(head)
                seqs = [[x for x in s if x != head] for s in seqs]
                seqs = [s for s in seqs if s]
                break
        else:
            for seq in seqs:
                result.extend(seq)
            break
    return result


# ─── Method / field / impl lookup ──────────────────────────────────

def find_method_in_hierarchy(session, class_name, method_name, repo_prefix, language='java', arg_count=None):
    """Find method by walking inheritance chain. Returns None if multiple overloads found."""
    ancestors = compute_mro(session, class_name, repo_prefix) if language == 'python' \
        else linear_ancestors(session, class_name, repo_prefix)

    for ancestor in ancestors:
        results = session.run("""
            MATCH (c {name: $cls})-[:CONTAINS]->(f:Function {name: $method})
            WHERE (c:Class OR c:Interface) AND c.path STARTS WITH $repo
            RETURN f.path AS path, c.name AS owner_class, f.line_number AS line_number, f.parameter_types AS ptypes
        """, cls=ancestor, method=method_name, repo=repo_prefix).data()
        if len(results) == 1:
            return results[0]
        elif len(results) > 1:
            if arg_count is not None:
                matched = [r for r in results
                           if isinstance(r.get('ptypes'), str) and r['ptypes'].count('"name":') == arg_count]
                if len(matched) == 1:
                    return matched[0]
            return None
    return None


def find_field_type_in_hierarchy(session, class_name, field_name, repo_prefix, language='java'):
    """Find field type by walking inheritance chain."""
    ancestors = compute_mro(session, class_name, repo_prefix) if language == 'python' \
        else linear_ancestors(session, class_name, repo_prefix)

    for ancestor in ancestors:
        result = session.run("""
            MATCH (v:Variable {name: $field, class_context: $cls})
            WHERE v.path STARTS WITH $repo
            RETURN v.type AS type LIMIT 1
        """, cls=ancestor, field=field_name, repo=repo_prefix).single()
        if result and result.get('type'):
            return result['type']
    return None


def find_impl_class(session, interface_name, repo_prefix):
    """Find implementation class for an interface (returns first match)."""
    result = session.run("""
        MATCH (impl:Class)-[:INHERITS]->(iface {name: $iface})
        WHERE impl.path STARTS WITH $repo
        RETURN impl.name AS name LIMIT 1
    """, iface=interface_name, repo=repo_prefix).single()
    return result['name'] if result else None


# ─── Local type environment ─────────────────────────────────────────

def build_local_type_env(file_data, session, repo_prefix):
    """Build scope-aware type map: {(scope, var_name): type_name}. Supports Tier 0/1/2."""
    env = {}
    # Tier 0+1: variables with type or value-inferred type
    for v in file_data.get('variables', []):
        scope = v.get('context', '') or ''
        vtype = v.get('type')
        if not vtype and v.get('value'):
            val = v['value'].split('(')[0].strip()
            if val and val[0:1].isupper():
                vtype = val
        if vtype:
            env[(scope, v['name'])] = vtype
    # Tier 0: field_declarations
    for f in file_data.get('field_declarations', []):
        if f.get('type'):
            env[(f.get('class_context', '') or '', f['name'])] = f['type']
    # Tier 2a: copy propagation (b = a, a already typed → b gets a's type)
    for _ in range(3):
        changed = False
        for v in file_data.get('variables', []):
            scope = v.get('context', '') or ''
            key = (scope, v['name'])
            if key in env:
                continue
            val = (v.get('value') or '').strip()
            if val and '(' not in val and val.isidentifier():
                for src_scope in (scope, ''):
                    if (src_scope, val) in env:
                        env[key] = env[(src_scope, val)]
                        changed = True
                        break
        if not changed:
            break
    # Tier 2b: callResult (x = func() → x gets func's return_type from DB)
    for v in file_data.get('variables', []):
        scope = v.get('context', '') or ''
        key = (scope, v['name'])
        if key in env:
            continue
        val = (v.get('value') or '').strip()
        if val and '(' in val:
            func_name = val.split('(')[0].strip().split('.')[-1]
            if func_name and func_name[0:1].islower():
                try:
                    ret = session.run("""
                        MATCH (f:Function {name: $fn})
                        WHERE f.path STARTS WITH $repo AND f.return_type IS NOT NULL
                        RETURN f.return_type AS rt LIMIT 1
                    """, fn=func_name, repo=repo_prefix).single()
                    if ret and ret['rt']:
                        rt = ret['rt'].split('<')[0].strip()
                        if rt and rt[0:1].isupper():
                            env[key] = rt
                except Exception:
                    pass
    return env


# ─── OVERRIDES creation ─────────────────────────────────────────────

def create_overrides(session, all_file_data):
    """Create OVERRIDES relationships: child.method → parent.method when both exist."""
    try:
        result = session.run("""
            MATCH (child:Class)-[:INHERITS]->(parent:Class)
            MATCH (child)-[:CONTAINS]->(cm:Function)
            MATCH (parent)-[:CONTAINS]->(pm:Function)
            WHERE cm.name = pm.name AND cm.name <> '__init__' AND cm.name <> 'constructor'
            MERGE (cm)-[:OVERRIDES]->(pm)
            RETURN count(*) AS created
        """)
        row = result.single()
        count = row['created'] if row else 0
        if count > 0:
            info_logger(f"Created {count} OVERRIDES relationships")
    except Exception as e:
        debug_log(f"OVERRIDES creation failed: {e}")
