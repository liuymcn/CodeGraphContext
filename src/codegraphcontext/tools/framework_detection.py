"""
Framework detection and injection relation creation.
V5.6: Injection annotations + Lombok + constructor injection.
V6.1: Framework-specific rules (Route, Bean, etc.) via FRAMEWORK_REGISTRY.
"""

from pathlib import Path
from codegraphcontext.utils.debug_log import debug_log, info_logger

# ── Injection annotations (cross-framework, no detection needed) ──

INJECTION_ANNOTATIONS = {'@Autowired', '@Resource', '@Inject', '@Value'}

COMPONENT_ANNOTATIONS = {'@Service', '@Component', '@Repository', '@Controller', '@RestController'}

LOMBOK_CONSTRUCTOR_ANNOTATIONS = {'@RequiredArgsConstructor', '@AllArgsConstructor'}


def create_injection_relations(session, all_file_data, repo_prefix):
    """Create INJECTS relations from annotations, constructor params, and Lombok."""
    total = 0

    for file_data in all_file_data:
        fields = file_data.get('field_declarations', [])
        classes = {c['name']: c for c in file_data.get('classes', [])}
        functions = file_data.get('functions', [])

        # 1. @Autowired/@Resource/@Inject field injection
        for field in fields:
            if any(ann in INJECTION_ANNOTATIONS for ann in field.get('decorators', [])):
                if _create_injects(session, field.get('class_context'), field.get('type'), field.get('name'), repo_prefix):
                    total += 1

        # 2. Constructor injection (@Service class with constructor params)
        for cls_name, cls in classes.items():
            cls_decorators = set(cls.get('decorators', []))
            if not cls_decorators.intersection(COMPONENT_ANNOTATIONS):
                continue

            # Find constructor (same name as class)
            for func in functions:
                if func.get('name') == cls_name and func.get('class_context') == cls_name:
                    import json as json_mod
                    param_types_raw = func.get('parameter_types')
                    if isinstance(param_types_raw, str):
                        try:
                            param_types = json_mod.loads(param_types_raw)
                        except Exception:
                            param_types = []
                    elif isinstance(param_types_raw, list):
                        param_types = param_types_raw
                    else:
                        param_types = []

                    for param in param_types:
                        if isinstance(param, dict) and param.get('type'):
                            if _create_injects(session, cls_name, param['type'], param.get('name', ''), repo_prefix):
                                total += 1

            # 3. Lombok: @RequiredArgsConstructor → final fields, @AllArgsConstructor → all fields
            if cls_decorators.intersection(LOMBOK_CONSTRUCTOR_ANNOTATIONS):
                all_args = '@AllArgsConstructor' in cls_decorators
                for field in fields:
                    if field.get('class_context') == cls_name and (all_args or field.get('is_final')):
                        if _create_injects(session, cls_name, field.get('type'), field.get('name'), repo_prefix):
                            total += 1

    if total > 0:
        info_logger(f"Created {total} INJECTS relations")
    return total


def _create_injects(session, owner_class, target_type, field_name, repo_prefix):
    """Create a single INJECTS relation. Returns True if created."""
    if not owner_class or not target_type:
        return False
    # Strip generics: List<User> → List, Map<K,V> → Map
    clean_type = target_type.split('<')[0].strip()
    # Skip primitive types
    if clean_type.lower() in ('string', 'int', 'long', 'boolean', 'double', 'float', 'void', 'byte', 'short', 'char'):
        return False
    try:
        result = session.run("""
            MATCH (owner:Class {name: $owner_class})
            WHERE owner.path STARTS WITH $repo_prefix
            MATCH (target) WHERE (target:Class OR target:Interface) AND target.name = $target_type
            AND target.path STARTS WITH $repo_prefix
            MERGE (owner)-[:INJECTS {field: $field_name}]->(target)
            RETURN count(*) AS c
        """, owner_class=owner_class, target_type=clean_type,
             field_name=field_name or '', repo_prefix=repo_prefix)
        row = result.single()
        return row is not None and row.get('c', 0) > 0
    except Exception as e:
        debug_log(f"Failed to create INJECTS {owner_class} → {clean_type}: {e}")
        return False


# ── V6.1 预留接口 ──

class FrameworkDetector:
    """Base class for framework-specific detection and relation creation."""
    name = "base"

    def detect(self, files, file_contents):
        return False

    def create_relations(self, session, all_file_data, repo_prefix):
        pass


FRAMEWORK_REGISTRY = {}


def detect_and_apply_frameworks(session, all_file_data, repo_prefix):
    """Detect frameworks and apply framework-specific rules. V5.6: no-op. V6.1: fills registry."""
    for name, detector in FRAMEWORK_REGISTRY.items():
        files = [fd.get('path', '') for fd in all_file_data]
        if detector.detect(files, {}):
            info_logger(f"Detected framework: {name}")
            detector.create_relations(session, all_file_data, repo_prefix)
