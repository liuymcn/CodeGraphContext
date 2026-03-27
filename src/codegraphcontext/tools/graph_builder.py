
# src/codegraphcontext/tools/graph_builder.py
import asyncio
import hashlib
import json as json_mod
import os
import pathspec
from pathlib import Path
from typing import Any, Coroutine, Dict, Optional, Tuple
from datetime import datetime

from ..core.database import DatabaseManager
from ..core.jobs import JobManager, JobStatus
from ..utils.debug_log import debug_log, info_logger, error_logger, warning_logger

# New imports for tree-sitter (using tree-sitter-language-pack)
from tree_sitter import Language, Parser
from ..utils.tree_sitter_manager import get_tree_sitter_manager
from ..cli.config_manager import get_config_value, CONFIG_DIR
import fnmatch
 
DEFAULT_IGNORE_PATTERNS = [
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.svg",
    "*.mp4",
    "*.mp3",
    "*.zip",
    "*.tar",
    "*.gz",
]

class TreeSitterParser:
    """A generic parser wrapper for a specific language using tree-sitter."""

    def __init__(self, language_name: str):
        self.language_name = language_name
        self.ts_manager = get_tree_sitter_manager()
        
        # Get the language (cached) and create a new parser for this instance
        self.language: Language = self.ts_manager.get_language_safe(language_name)
        # In tree-sitter 0.25+, Parser takes language in constructor
        self.parser = Parser(self.language)

        self.language_specific_parser = None
        if self.language_name == 'python':
            from .languages.python import PythonTreeSitterParser
            self.language_specific_parser = PythonTreeSitterParser(self)
        elif self.language_name == 'javascript':
            from .languages.javascript import JavascriptTreeSitterParser
            self.language_specific_parser = JavascriptTreeSitterParser(self)
        elif self.language_name == 'go':
            from .languages.go import GoTreeSitterParser
            self.language_specific_parser = GoTreeSitterParser(self)
        elif self.language_name == 'typescript':
            from .languages.typescript import TypescriptTreeSitterParser
            self.language_specific_parser = TypescriptTreeSitterParser(self)
        elif self.language_name == 'cpp':
            from .languages.cpp import CppTreeSitterParser
            self.language_specific_parser = CppTreeSitterParser(self)
        elif self.language_name == 'rust':
            from .languages.rust import RustTreeSitterParser
            self.language_specific_parser = RustTreeSitterParser(self)
        elif self.language_name == 'c':
            from .languages.c import CTreeSitterParser
            self.language_specific_parser = CTreeSitterParser(self)
        elif self.language_name == 'java':
            from .languages.java import JavaTreeSitterParser
            self.language_specific_parser = JavaTreeSitterParser(self)
        elif self.language_name == 'ruby':
            from .languages.ruby import RubyTreeSitterParser
            self.language_specific_parser = RubyTreeSitterParser(self)
        elif self.language_name == 'c_sharp':
            from .languages.csharp import CSharpTreeSitterParser
            self.language_specific_parser = CSharpTreeSitterParser(self)
        elif self.language_name == 'php':
            from .languages.php import PhpTreeSitterParser
            self.language_specific_parser = PhpTreeSitterParser(self)
        elif self.language_name == 'kotlin':
            from .languages.kotlin import KotlinTreeSitterParser
            self.language_specific_parser = KotlinTreeSitterParser(self)
        elif self.language_name == 'scala':
            from .languages.scala import ScalaTreeSitterParser
            self.language_specific_parser = ScalaTreeSitterParser(self)
        elif self.language_name == 'swift':
            from .languages.swift import SwiftTreeSitterParser
            self.language_specific_parser = SwiftTreeSitterParser(self)
        elif self.language_name == 'haskell':
            from .languages.haskell import HaskellTreeSitterParser
            self.language_specific_parser = HaskellTreeSitterParser(self)
        elif self.language_name == 'dart':
            from .languages.dart import DartTreeSitterParser
            self.language_specific_parser = DartTreeSitterParser(self)
        elif self.language_name == 'perl':
            from .languages.perl import PerlTreeSitterParser
            self.language_specific_parser = PerlTreeSitterParser(self)
        elif self.language_name == 'elixir':
            from .languages.elixir import ElixirTreeSitterParser
            self.language_specific_parser = ElixirTreeSitterParser(self)



    def parse(self, path: Path, is_dependency: bool = False, **kwargs) -> Dict:
        """Dispatches parsing to the language-specific parser."""
        if self.language_specific_parser:
            return self.language_specific_parser.parse(path, is_dependency, **kwargs)
        else:
            raise NotImplementedError(f"No language-specific parser implemented for {self.language_name}")

class GraphBuilder:
    """Module for building and managing the Neo4j code graph."""

    def __init__(self, db_manager: DatabaseManager, job_manager: JobManager, loop: asyncio.AbstractEventLoop):
        self.db_manager = db_manager
        self.job_manager = job_manager
        self.loop = loop
        self.driver = self.db_manager.get_driver()
        self.parsers = {
            '.py': TreeSitterParser('python'),
            '.ipynb': TreeSitterParser('python'),
            '.js': TreeSitterParser('javascript'),
            '.jsx': TreeSitterParser('javascript'),
            '.mjs': TreeSitterParser('javascript'),
            '.cjs': TreeSitterParser('javascript'),
            '.go': TreeSitterParser('go'),
            '.ts': TreeSitterParser('typescript'),
            '.tsx': TreeSitterParser('typescript'),
            '.cpp': TreeSitterParser('cpp'),
            '.h': TreeSitterParser('cpp'),
            '.hpp': TreeSitterParser('cpp'),
            '.hh': TreeSitterParser('cpp'),
            '.rs': TreeSitterParser('rust'),
            '.c': TreeSitterParser('c'),
            # '.h': TreeSitterParser('c'), # Need to write an algo for distinguishing C vs C++ headers
            '.java': TreeSitterParser('java'),
            '.rb': TreeSitterParser('ruby'),
            '.cs': TreeSitterParser('c_sharp'),
            '.php': TreeSitterParser('php'),
            '.kt': TreeSitterParser('kotlin'),
            '.scala': TreeSitterParser('scala'),
            '.sc': TreeSitterParser('scala'),
            '.swift': TreeSitterParser('swift'),
            '.hs': TreeSitterParser('haskell'),
            '.dart': TreeSitterParser('dart'),
            '.pl': TreeSitterParser('perl'),
            '.pm': TreeSitterParser('perl'),
            '.ex': TreeSitterParser('elixir'),
            '.exs': TreeSitterParser('elixir'),
        }
        self.create_schema()

    # A general schema creation based on common features across languages
    def create_schema(self):
        """Create constraints and indexes in Neo4j."""
        # When adding a new node type with a unique key, add its constraint here.
        with self.driver.session() as session:
            try:
                session.run("CREATE CONSTRAINT repository_path IF NOT EXISTS FOR (r:Repository) REQUIRE r.path IS UNIQUE")
                session.run("CREATE CONSTRAINT path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE")
                session.run("CREATE CONSTRAINT directory_path IF NOT EXISTS FOR (d:Directory) REQUIRE d.path IS UNIQUE")
                session.run("CREATE CONSTRAINT function_unique IF NOT EXISTS FOR (f:Function) REQUIRE (f.name, f.path, f.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT class_unique IF NOT EXISTS FOR (c:Class) REQUIRE (c.name, c.path, c.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT trait_unique IF NOT EXISTS FOR (t:Trait) REQUIRE (t.name, t.path, t.line_number) IS UNIQUE") # Added trait constraint
                session.run("CREATE CONSTRAINT interface_unique IF NOT EXISTS FOR (i:Interface) REQUIRE (i.name, i.path, i.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT macro_unique IF NOT EXISTS FOR (m:Macro) REQUIRE (m.name, m.path, m.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT variable_unique IF NOT EXISTS FOR (v:Variable) REQUIRE (v.name, v.path, v.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT module_name IF NOT EXISTS FOR (m:Module) REQUIRE m.name IS UNIQUE")
                session.run("CREATE CONSTRAINT struct_cpp IF NOT EXISTS FOR (cstruct: Struct) REQUIRE (cstruct.name, cstruct.path, cstruct.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT enum_cpp IF NOT EXISTS FOR (cenum: Enum) REQUIRE (cenum.name, cenum.path, cenum.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT union_cpp IF NOT EXISTS FOR (cunion: Union) REQUIRE (cunion.name, cunion.path, cunion.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT annotation_unique IF NOT EXISTS FOR (a:Annotation) REQUIRE (a.name, a.path, a.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT record_unique IF NOT EXISTS FOR (r:Record) REQUIRE (r.name, r.path, r.line_number) IS UNIQUE")
                session.run("CREATE CONSTRAINT property_unique IF NOT EXISTS FOR (p:Property) REQUIRE (p.name, p.path, p.line_number) IS UNIQUE")
                
                # Indexes for language attribute
                session.run("CREATE INDEX function_lang IF NOT EXISTS FOR (f:Function) ON (f.lang)")
                session.run("CREATE INDEX class_lang IF NOT EXISTS FOR (c:Class) ON (c.lang)")
                session.run("CREATE INDEX annotation_lang IF NOT EXISTS FOR (a:Annotation) ON (a.lang)")
                is_falkordb = getattr(self.db_manager, 'get_backend_type', lambda: 'neo4j')() != 'neo4j'
                if is_falkordb:
                    # FalkorDB uses db.idx.fulltext.createNodeIndex per label
                    for label in ['Function', 'Class']:
                        try:
                            session.run(f"CALL db.idx.fulltext.createNodeIndex('{label}', 'name', 'source', 'docstring')")
                        except Exception:
                            pass  # Index may already exist
                else:
                    session.run("""
                        CREATE FULLTEXT INDEX code_search_index IF NOT EXISTS
                        FOR (n:Function|Class|Variable)
                        ON EACH [n.name, n.source, n.docstring]
                    """)
                
                info_logger("Database schema verified/created successfully")
            except Exception as e:
                warning_logger(f"Schema creation warning: {e}")

    # --- #6: First-index CREATE optimization ---
    def _is_db_empty(self) -> bool:
        """Check if the database has no Repository nodes (first-time index)."""
        try:
            with self.driver.session() as session:
                result = session.run("MATCH (r:Repository) RETURN count(r) AS c")
                row = result.single()
                return row is not None and row['c'] == 0
        except Exception:
            return False

    # --- #8: Parse cache helpers ---
    @staticmethod
    def _get_cache_dir() -> Path:
        d = CONFIG_DIR / "cgc_cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _cache_key(file_path: Path) -> str:
        return hashlib.md5(str(file_path.resolve()).encode()).hexdigest()

    @staticmethod
    def _file_fingerprint(file_path: Path) -> str:
        """mtime + size fingerprint for change detection."""
        st = file_path.stat()
        return f"{st.st_mtime_ns}:{st.st_size}"

    def _load_cached_parse(self, file_path: Path) -> Optional[Dict]:
        """Load cached parse result if file hasn't changed."""
        cache_dir = self._get_cache_dir()
        key = self._cache_key(file_path)
        cache_file = cache_dir / f"{key}.json"
        if not cache_file.exists():
            return None
        try:
            data = json_mod.loads(cache_file.read_text(encoding='utf-8'))
            if data.get('_fingerprint') == self._file_fingerprint(file_path):
                data.pop('_fingerprint', None)
                return data
        except Exception:
            pass
        return None

    def _save_parse_cache(self, file_path: Path, file_data: Dict):
        """Save parse result to cache."""
        cache_dir = self._get_cache_dir()
        key = self._cache_key(file_path)
        cache_file = cache_dir / f"{key}.json"
        try:
            to_save = file_data.copy()
            to_save['_fingerprint'] = self._file_fingerprint(file_path)
            cache_file.write_text(json_mod.dumps(to_save, default=str, ensure_ascii=False), encoding='utf-8')
        except Exception as e:
            debug_log(f"Failed to save parse cache for {file_path}: {e}")

    # --- #5: Incremental indexing helpers ---
    @staticmethod
    def _get_index_meta_path() -> Path:
        return CONFIG_DIR / "cgc_cache" / "_index_meta.json"

    def _load_index_meta(self) -> Dict:
        p = self._get_index_meta_path()
        if p.exists():
            try:
                return json_mod.loads(p.read_text(encoding='utf-8'))
            except Exception:
                pass
        return {}

    def _save_index_meta(self, meta: Dict):
        p = self._get_index_meta_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(json_mod.dumps(meta, default=str, ensure_ascii=False), encoding='utf-8')
        except Exception as e:
            debug_log(f"Failed to save index meta: {e}")

    def _pre_scan_for_imports(self, files: list[Path]) -> dict:
        """Dispatches pre-scan to the correct language-specific implementation."""
        imports_map = {}
        
        # Group files by language/extension
        files_by_lang = {}
        for file in files:
            if file.suffix in self.parsers:
                lang_ext = file.suffix
                if lang_ext not in files_by_lang:
                    files_by_lang[lang_ext] = []
                files_by_lang[lang_ext].append(file)

        if '.py' in files_by_lang:
            from .languages import python as python_lang_module
            imports_map.update(python_lang_module.pre_scan_python(files_by_lang['.py'], self.parsers['.py']))
        if '.ipynb' in files_by_lang:
            from .languages import python as python_lang_module
            imports_map.update(python_lang_module.pre_scan_python(files_by_lang['.ipynb'], self.parsers['.ipynb']))
        if '.js' in files_by_lang:
            from .languages import javascript as js_lang_module
            imports_map.update(js_lang_module.pre_scan_javascript(files_by_lang['.js'], self.parsers['.js']))
        if '.jsx' in files_by_lang:
            from .languages import javascript as js_lang_module
            imports_map.update(js_lang_module.pre_scan_javascript(files_by_lang['.jsx'], self.parsers['.jsx']))
        if '.mjs' in files_by_lang:
            from .languages import javascript as js_lang_module
            imports_map.update(js_lang_module.pre_scan_javascript(files_by_lang['.mjs'], self.parsers['.mjs']))
        if '.cjs' in files_by_lang:
            from .languages import javascript as js_lang_module
            imports_map.update(js_lang_module.pre_scan_javascript(files_by_lang['.cjs'], self.parsers['.cjs']))
        if '.go' in files_by_lang:
             from .languages import go as go_lang_module
             imports_map.update(go_lang_module.pre_scan_go(files_by_lang['.go'], self.parsers['.go']))
        if '.ts' in files_by_lang:
            from .languages import typescript as ts_lang_module
            imports_map.update(ts_lang_module.pre_scan_typescript(files_by_lang['.ts'], self.parsers['.ts']))
        if '.tsx' in files_by_lang:
            from .languages import typescriptjsx as tsx_lang_module
            imports_map.update(tsx_lang_module.pre_scan_typescript(files_by_lang['.tsx'], self.parsers['.tsx']))
        if '.cpp' in files_by_lang:
            from .languages import cpp as cpp_lang_module
            imports_map.update(cpp_lang_module.pre_scan_cpp(files_by_lang['.cpp'], self.parsers['.cpp']))
        if '.h' in files_by_lang:
            from .languages import cpp as cpp_lang_module
            imports_map.update(cpp_lang_module.pre_scan_cpp(files_by_lang['.h'], self.parsers['.h']))
        if '.hpp' in files_by_lang:
            from .languages import cpp as cpp_lang_module
            imports_map.update(cpp_lang_module.pre_scan_cpp(files_by_lang['.hpp'], self.parsers['.hpp']))
        if '.hh' in files_by_lang:
            from .languages import cpp as cpp_lang_module
            imports_map.update(cpp_lang_module.pre_scan_cpp(files_by_lang['.hh'], self.parsers['.hh']))
        if '.rs' in files_by_lang:
            from .languages import rust as rust_lang_module
            imports_map.update(rust_lang_module.pre_scan_rust(files_by_lang['.rs'], self.parsers['.rs']))
        if '.c' in files_by_lang:
            from .languages import c as c_lang_module
            imports_map.update(c_lang_module.pre_scan_c(files_by_lang['.c'], self.parsers['.c']))
        elif '.java' in files_by_lang:
            from .languages import java as java_lang_module
            imports_map.update(java_lang_module.pre_scan_java(files_by_lang['.java'], self.parsers['.java']))
        elif '.rb' in files_by_lang:
            from .languages import ruby as ruby_lang_module
            imports_map.update(ruby_lang_module.pre_scan_ruby(files_by_lang['.rb'], self.parsers['.rb']))
        elif '.cs' in files_by_lang:
            from .languages import csharp as csharp_lang_module
            imports_map.update(csharp_lang_module.pre_scan_csharp(files_by_lang['.cs'], self.parsers['.cs']))
        if '.kt' in files_by_lang:
            from .languages import kotlin as kotlin_lang_module
            imports_map.update(kotlin_lang_module.pre_scan_kotlin(files_by_lang['.kt'], self.parsers['.kt']))
        if '.scala' in files_by_lang:
            from .languages import scala as scala_lang_module
            imports_map.update(scala_lang_module.pre_scan_scala(files_by_lang['.scala'], self.parsers['.scala']))
        if '.sc' in files_by_lang:
            from .languages import scala as scala_lang_module
            imports_map.update(scala_lang_module.pre_scan_scala(files_by_lang['.sc'], self.parsers['.sc']))
        if '.swift' in files_by_lang:
            from .languages import swift as swift_lang_module
            imports_map.update(swift_lang_module.pre_scan_swift(files_by_lang['.swift'], self.parsers['.swift']))
        if '.dart' in files_by_lang:
            from .languages import dart as dart_lang_module
            imports_map.update(dart_lang_module.pre_scan_dart(files_by_lang['.dart'], self.parsers['.dart']))
        if '.pl' in files_by_lang:
            from .languages import perl as perl_lang_module
            imports_map.update(perl_lang_module.pre_scan_perl(files_by_lang['.pl'], self.parsers['.pl']))
        if '.pm' in files_by_lang:
            from .languages import perl as perl_lang_module
            imports_map.update(perl_lang_module.pre_scan_perl(files_by_lang['.pm'], self.parsers['.pm']))
        if '.ex' in files_by_lang:
            from .languages import elixir as elixir_lang_module
            imports_map.update(elixir_lang_module.pre_scan_elixir(files_by_lang['.ex'], self.parsers['.ex']))
        if '.exs' in files_by_lang:
            from .languages import elixir as elixir_lang_module
            imports_map.update(elixir_lang_module.pre_scan_elixir(files_by_lang['.exs'], self.parsers['.exs']))

        return imports_map

    # Language-agnostic method
    def add_repository_to_graph(self, repo_path: Path, is_dependency: bool = False):
        """Adds a repository node using its absolute path as the unique key."""
        repo_name = repo_path.name
        repo_path_str = str(repo_path.resolve())
        with self.driver.session() as session:
            session.run(
                """
                MERGE (r:Repository {path: $path})
                SET r.name = $name, r.is_dependency = $is_dependency
                """,
                path=repo_path_str,
                name=repo_name,
                is_dependency=is_dependency,
            )

    # First pass to add file and its contents
    def add_file_to_graph(self, file_data: Dict, repo_name: str, imports_map: dict, use_create: bool = False):
        """Adds a file and its contents within a single, unified session."""
        calls_count = len(file_data.get('function_calls', []))
        debug_log(f"Executing add_file_to_graph for {file_data.get('path', 'unknown')} - Calls found: {calls_count}")
        file_path_str = str(Path(file_data['path']).resolve())
        file_name = Path(file_path_str).name
        is_dependency = file_data.get('is_dependency', False)
        # #6: Use CREATE for first-time index, MERGE otherwise
        write_cmd = "CREATE" if use_create else "MERGE"

        with self.driver.session() as session:
            try:
                # Match repository by path, not name, to avoid conflicts with same-named folders at different locations
                repo_result = session.run("MATCH (r:Repository {path: $repo_path}) RETURN r.path as path", repo_path=str(Path(file_data['repo_path']).resolve())).single()
                relative_path = str(Path(file_path_str).relative_to(Path(repo_result['path']))) if repo_result else file_name
            except ValueError:
                relative_path = file_name

            session.run(f"""
                {write_cmd} (f:File {{path: $path}})
                SET f.name = $name, f.relative_path = $relative_path, f.is_dependency = $is_dependency
            """, path=file_path_str, name=file_name, relative_path=relative_path, is_dependency=is_dependency)

            file_path_obj = Path(file_path_str)
            if repo_result:
                repo_path_obj = Path(repo_result['path'])
            else:
                # Fallback to the path we queried for
                warning_logger(f"Repository node not found for {file_data['repo_path']} during indexing of {file_name}. Using original path.")
                repo_path_obj = Path(file_data['repo_path']).resolve()
            
            relative_path_to_file = file_path_obj.relative_to(repo_path_obj)
            
            parent_path = str(repo_path_obj)
            parent_label = 'Repository'

            for part in relative_path_to_file.parts[:-1]:
                current_path = Path(parent_path) / part
                current_path_str = str(current_path)
                
                session.run(f"""
                    MATCH (p:{parent_label} {{path: $parent_path}})
                    {write_cmd} (d:Directory {{path: $current_path}})
                    SET d.name = $part
                    {write_cmd} (p)-[:CONTAINS]->(d)
                """, parent_path=parent_path, current_path=current_path_str, part=part)

                parent_path = current_path_str
                parent_label = 'Directory'

            session.run(f"""
                MATCH (p:{parent_label} {{path: $parent_path}})
                MATCH (f:File {{path: $path}})
                {write_cmd} (p)-[:CONTAINS]->(f)
            """, parent_path=parent_path, path=file_path_str)

            # CONTAINS relationships for functions, classes, and variables
            # To add a new language-specific node type (e.g., 'Trait' for Rust):
            # 1. Ensure your language-specific parser returns a list under a unique key (e.g., 'traits': [...] ).
            # 2. Add a new constraint for the new label in the `create_schema` method.
            # 3. Add a new entry to the `item_mappings` list below (e.g., (file_data.get('traits', []), 'Trait') ).
            item_mappings = [
                (file_data.get('functions', []), 'Function'),
                (file_data.get('classes', []), 'Class'),
                (file_data.get('traits', []), 'Trait'), # <-- Added trait mapping
                (file_data.get('variables', []), 'Variable'),
                (file_data.get('interfaces', []), 'Interface'),
                (file_data.get('macros', []), 'Macro'),
                (file_data.get('structs',[]), 'Struct'),
                (file_data.get('enums',[]), 'Enum'),
                (file_data.get('unions',[]), 'Union'),
                (file_data.get('records',[]), 'Record'),
                (file_data.get('properties',[]), 'Property'),
            ]
            for item_data, label in item_mappings:
                if not item_data:
                    continue
                # Ensure cyclomatic_complexity is set for functions
                if label == 'Function':
                    for item in item_data:
                        if 'cyclomatic_complexity' not in item:
                            item['cyclomatic_complexity'] = 1

                # Batch write nodes with UNWIND
                session.run(f"""
                    UNWIND $items AS item
                    MATCH (f:File {{path: $path}})
                    {write_cmd} (n:{label} {{name: item.name, path: $path, line_number: item.line_number}})
                    SET n += item
                    {write_cmd} (f)-[:CONTAINS]->(n)
                """, path=file_path_str, items=item_data)

                # Batch write parameters for functions
                if label == 'Function':
                    params_batch = []
                    for item in item_data:
                        for arg_name in item.get('args', []):
                            params_batch.append({
                                'func_name': item['name'],
                                'line_number': item['line_number'],
                                'arg_name': arg_name
                            })
                    if params_batch:
                        session.run(f"""
                            UNWIND $params AS p
                            MATCH (fn:Function {{name: p.func_name, path: $path, line_number: p.line_number}})
                            {write_cmd} (param:Parameter {{name: p.arg_name, path: $path, function_line_number: p.line_number}})
                            {write_cmd} (fn)-[:HAS_PARAMETER]->(param)
                        """, path=file_path_str, params=params_batch)

            # --- NEW: persist Ruby Modules ---
            for m in file_data.get('modules', []):
                session.run("""
                    MERGE (mod:Module {name: $name})
                    ON CREATE SET mod.lang = $lang
                    ON MATCH  SET mod.lang = coalesce(mod.lang, $lang)
                """, name=m["name"], lang=file_data.get("lang"))

            # Create CONTAINS relationships for nested functions
            for item in file_data.get('functions', []):
                if item.get("context_type") == "function_definition":
                    session.run("""
                        MATCH (outer:Function {name: $context, path: $path})
                        MATCH (inner:Function {name: $name, path: $path, line_number: $line_number})
                        MERGE (outer)-[:CONTAINS]->(inner)
                    """, context=item["context"], path=file_path_str, name=item["name"], line_number=item["line_number"])

            # Handle imports and create IMPORTS relationships
            for imp in file_data.get('imports', []):
                info_logger(f"Processing import: {imp}")
                lang = file_data.get('lang')
                if lang == 'javascript':
                    # New, correct logic for JS
                    module_name = imp.get('source')
                    if not module_name: continue

                    # Use a map for relationship properties to handle optional alias and line_number
                    rel_props = {'imported_name': imp.get('name', '*')}
                    if imp.get('alias'):
                        rel_props['alias'] = imp.get('alias')
                    if imp.get('line_number'):
                        rel_props['line_number'] = imp.get('line_number')

                    session.run("""
                        MATCH (f:File {path: $path})
                        MERGE (m:Module {name: $module_name})
                        MERGE (f)-[r:IMPORTS]->(m)
                        SET r += $props
                    """, path=file_path_str, module_name=module_name, props=rel_props)
                else:
                    # Existing logic for Python (and other languages)
                    # For KùzuDB, Module schema only has: name, lang, full_import_name.
                    # 'alias' belongs on the relationship.
                    
                    set_clauses = []
                    if 'full_import_name' in imp:
                        set_clauses.append("m.full_import_name = $full_import_name")
                    
                    set_clause_str = ("SET " + ", ".join(set_clauses)) if set_clauses else ""

                    # Build relationship properties
                    rel_props = {}
                    if imp.get('line_number'):
                        rel_props['line_number'] = imp.get('line_number')
                    if imp.get('alias'):
                        rel_props['alias'] = imp.get('alias')
                    
                    # Ensure full_import_name is available in params for SET clause
                    params = imp.copy()
                    params['path'] = file_path_str
                    params['rel_props'] = rel_props
                    params['module_name'] = imp.get('name') # Use 'name' from imp as module name

                    session.run(f"""
                        MATCH (f:File {{path: $path}})
                        MERGE (m:Module {{name: $module_name}})
                        {set_clause_str}
                        MERGE (f)-[r:IMPORTS]->(m)
                        SET r += $rel_props
                    """, **params)


            # Handle CONTAINS relationship between class to their children like variables
            for func in file_data.get('functions', []):
                if func.get('class_context'):
                    session.run("""
                        MATCH (c:Class {name: $class_name, path: $path})
                        MATCH (fn:Function {name: $func_name, path: $path, line_number: $func_line})
                        MERGE (c)-[:CONTAINS]->(fn)
                    """, 
                    class_name=func['class_context'],
                    path=file_path_str,
                    func_name=func['name'],
                    func_line=func['line_number'])

            # --- NEW: Class INCLUDES Module (Ruby mixins) ---
            for inc in file_data.get('module_inclusions', []):
                session.run("""
                    MATCH (c:Class {name: $class_name, path: $path})
                    MERGE (m:Module {name: $module_name})
                    MERGE (c)-[:INCLUDES]->(m)
                """,
                class_name=inc["class"],
                path=file_path_str,
                module_name=inc["module"])

            # Class inheritance is handled in a separate pass after all files are processed.
            # Function calls are also handled in a separate pass after all files are processed.

    # Second pass to create relationships that depend on all files being present like call functions and class inheritance
    def _safe_run_create(self, session, query, params) -> bool:
        """Helper to run a creation query safely, catching exceptions and checking result."""
        try:
            result = session.run(query, **params)
            row = result.single()
            return row is not None and row.get('created', 0) > 0
        except Exception as e:
            # Optionally log, but suppress to allow fallback
            return False

    def _create_function_calls(self, session, file_data: Dict, imports_map: dict):
        """Create CALLS relationships with a unified, prioritized logic flow for all call types."""
        caller_file_path = str(Path(file_data['path']).resolve())
        num_calls = len(file_data.get('function_calls', []))
        if num_calls > 0:
            debug_log(f"Creating function calls for {caller_file_path} (Count: {num_calls})")
        
        local_names = {f['name'] for f in file_data.get('functions', [])} | \
                      {c['name'] for c in file_data.get('classes', [])}
        local_imports = {imp.get('alias') or imp['name'].split('.')[-1]: imp['name'] 
                        for imp in file_data.get('imports', [])}
        
        # Check if we should skip external resolution attempts - 
        skip_external = (get_config_value("SKIP_EXTERNAL_RESOLUTION") or "false").lower() == "true"
        
        for call in file_data.get('function_calls', []):
            called_name = call['name']
            # debug_log(f"Processing call: {called_name}")
            if called_name in __builtins__: continue

            resolved_path = None
            full_call = call.get('full_name', called_name)
            base_obj = full_call.split('.')[0] if '.' in full_call else None
            
            # For chained calls like self.graph_builder.method(), we need to look up 'method'
            # For direct calls like self.method(), we can use the caller's file
            is_chained_call = full_call.count('.') > 1 if '.' in full_call else False
            
            # Determine the lookup name:
            # - For chained calls (self.attr.method), use the actual method name
            # - For direct calls (self.method or module.function), use the base object
            if is_chained_call and base_obj in ('self', 'this', 'super', 'super()', 'cls', '@'):
                lookup_name = called_name  # Use the actual method name for lookup
            else:
                lookup_name = base_obj if base_obj else called_name

            # 1. Check for local context keywords/direct local names
            # Only resolve to caller_file_path for DIRECT self/this calls, not chained ones
            if base_obj in ('self', 'this', 'super', 'super()', 'cls', '@') and not is_chained_call:
                resolved_path = caller_file_path
            elif lookup_name in local_names:
                resolved_path = caller_file_path
            
            # 2. Check inferred type if available
            elif call.get('inferred_obj_type'):
                obj_type = call['inferred_obj_type']
                possible_paths = imports_map.get(obj_type, [])
                if len(possible_paths) > 0:
                    resolved_path = possible_paths[0]
            
            # 3. Check imports map with validation against local imports
            if not resolved_path:
                possible_paths = imports_map.get(lookup_name, [])
                if len(possible_paths) == 1:
                    resolved_path = possible_paths[0]
                elif len(possible_paths) > 1:
                    if lookup_name in local_imports:
                        full_import_name = local_imports[lookup_name]
                        
                        # Optimization: Check if the FQN is directly in imports_map (from pre-scan)
                        if full_import_name in imports_map:
                             direct_paths = imports_map[full_import_name]
                             if direct_paths and len(direct_paths) == 1:
                                 resolved_path = direct_paths[0]
                        
                        if not resolved_path:
                            for path in possible_paths:
                                if full_import_name.replace('.', '/') in path:
                                    resolved_path = path
                                    break
            
            if not resolved_path:
                # Only log warning if we're not skipping external resolution
                if not skip_external:
                    warning_logger(f"Could not resolve call {called_name} (lookup: {lookup_name}) in {caller_file_path}")
                # Track that this was an unresolved external call
                is_unresolved_external = True
            else:
                is_unresolved_external = False
            # else:
            #      info_logger(f"Resolved call {called_name} -> {resolved_path}")
            
            # Legacy fallback block (was mis-indented)
            if not resolved_path:
                possible_paths = imports_map.get(lookup_name, [])
                if len(possible_paths) > 0:
                     # Final fallback: global candidate
                     # Check if it was imported explicitly, otherwise risky
                     if lookup_name in local_imports:
                         # We already tried specific matching above, but if we are here
                         # it means we had ambiguity without matching path?
                         pass
                     else:
                        # Fallback to first available if not imported? Or skip?
                        # Original logic: resolved_path = possible_paths[0]
                        # But wait, original code logic was:
                        pass
            if not resolved_path:
                if called_name in local_names:
                    resolved_path = caller_file_path
                    is_unresolved_external = False  # This is a local call, not external
                elif called_name in imports_map and imports_map[called_name]:
                    # Check if any path in imports_map for called_name matches current file's imports
                    candidates = imports_map[called_name]
                    for path in candidates:
                        for imp_name in local_imports.values():
                            if imp_name.replace('.', '/') in path:
                                resolved_path = path
                                is_unresolved_external = False  # Found a match
                                break
                        if resolved_path: break
                    if not resolved_path:
                        resolved_path = candidates[0]
                else:
                    resolved_path = caller_file_path
            
            # Skip creating CALLS relationship for unresolved external calls when skip_external is enabled
            if skip_external and is_unresolved_external:
                continue

            caller_context = call.get('context')
            if caller_context and len(caller_context) == 3 and caller_context[0] is not None:
                caller_name, _, caller_line_number = caller_context
                
                call_params = {
                    'caller_name': caller_name,
                    'caller_file_path': caller_file_path,
                    'caller_line_number': caller_line_number,
                    'called_name': called_name,
                    'called_file_path': resolved_path,
                    'line_number': call['line_number'],
                    'args': call.get('args', []),
                    'full_call_name': call.get('full_name', called_name)
                }
                
                # #9: Merged COALESCE query — replaces 5-step cascade with 1 DB round-trip
                # Priority: Function > Class for caller; Function > __init__ > Class for target
                if not self._safe_run_create(session, """
                    OPTIONAL MATCH (cf:Function {name: $caller_name, path: $caller_file_path})
                    OPTIONAL MATCH (cc:Class {name: $caller_name, path: $caller_file_path})
                    WITH COALESCE(cf, cc) AS caller
                    WHERE caller IS NOT NULL
                    OPTIONAL MATCH (tf:Function {name: $called_name, path: $called_file_path})
                    OPTIONAL MATCH (tc:Class {name: $called_name, path: $called_file_path})
                    OPTIONAL MATCH (tc)-[:CONTAINS]->(init:Function)
                    WHERE init.name IN ["__init__", "constructor"]
                    WITH caller, COALESCE(tf, init, tc) AS target
                    WHERE target IS NOT NULL
                    MERGE (caller)-[:CALLS {line_number: $line_number, args: $args, full_call_name: $full_call_name}]->(target)
                    RETURN count(*) as created
                """, call_params):
                    # Fallback: global search without path constraint on callee
                    self._safe_run_create(session, """
                        OPTIONAL MATCH (cf:Function {name: $caller_name, path: $caller_file_path})
                        OPTIONAL MATCH (cc:Class {name: $caller_name, path: $caller_file_path})
                        WITH COALESCE(cf, cc) AS caller
                        WHERE caller IS NOT NULL
                        OPTIONAL MATCH (called:Function {name: $called_name})
                        WITH caller, called
                        WHERE called IS NOT NULL
                        MERGE (caller)-[:CALLS {line_number: $line_number, args: $args, full_call_name: $full_call_name}]->(called)
                    """, call_params)
            else:
                # File-level calls
                call_params = {
                    'caller_file_path': caller_file_path,
                    'called_name': called_name,
                    'called_file_path': resolved_path,
                    'line_number': call['line_number'],
                    'args': call.get('args', []),
                    'full_call_name': call.get('full_name', called_name)
                }
                
                # #9: Merged COALESCE for file-level calls
                if not self._safe_run_create(session, """
                    OPTIONAL MATCH (caller:File {path: $caller_file_path})
                    WHERE caller IS NOT NULL
                    OPTIONAL MATCH (tf:Function {name: $called_name, path: $called_file_path})
                    OPTIONAL MATCH (tc:Class {name: $called_name, path: $called_file_path})
                    OPTIONAL MATCH (tc)-[:CONTAINS]->(init:Function)
                    WHERE init.name IN ["__init__", "constructor"]
                    WITH caller, COALESCE(tf, init, tc) AS target
                    WHERE target IS NOT NULL
                    MERGE (caller)-[:CALLS {line_number: $line_number, args: $args, full_call_name: $full_call_name}]->(target)
                    RETURN count(*) as created
                """, call_params):
                    # Fallback: global search
                    self._safe_run_create(session, """
                        OPTIONAL MATCH (caller:File {path: $caller_file_path})
                        OPTIONAL MATCH (called:Function {name: $called_name})
                        WITH caller, called
                        WHERE caller IS NOT NULL AND called IS NOT NULL
                        MERGE (caller)-[:CALLS {line_number: $line_number, args: $args, full_call_name: $full_call_name}]->(called)
                    """, call_params)

    def _create_all_function_calls(self, all_file_data: list[Dict], imports_map: dict, job_id: str = None):
        """Create CALLS relationships for all functions after all files have been processed."""
        total = len(all_file_data)
        if job_id:
            self.job_manager.update_job(job_id, stage="function_calls", total_files=total, processed_files=0, current_file="")
        debug_log(f"_create_all_function_calls called with {total} files")
        with self.driver.session() as session:
            for idx, file_data in enumerate(all_file_data):
                debug_log(f"Processing file {idx+1}/{total}: {file_data.get('path', 'unknown')}")
                self._create_function_calls(session, file_data, imports_map)
                if job_id:
                    self.job_manager.update_job(job_id, processed_files=idx + 1)

    def _create_inheritance_links(self, session, file_data: Dict, imports_map: dict):
        """Create INHERITS relationships with a more robust resolution logic."""
        caller_file_path = str(Path(file_data['path']).resolve())
        local_class_names = {c['name'] for c in file_data.get('classes', [])}
        # Create a map of local import aliases/names to full import names
        local_imports = {imp.get('alias') or imp['name'].split('.')[-1]: imp['name']
                         for imp in file_data.get('imports', [])}

        for class_item in file_data.get('classes', []):
            if not class_item.get('bases'):
                continue

            for base_class_str in class_item['bases']:
                if base_class_str == 'object':
                    continue

                resolved_path = None
                target_class_name = base_class_str.split('.')[-1]

                # Handle qualified names like module.Class or alias.Class
                if '.' in base_class_str:
                    lookup_name = base_class_str.split('.')[0]
                    
                    # Case 1: The prefix is a known import
                    if lookup_name in local_imports:
                        full_import_name = local_imports[lookup_name]
                        possible_paths = imports_map.get(target_class_name, [])
                        # Find the path that corresponds to the imported module
                        for path in possible_paths:
                            if full_import_name.replace('.', '/') in path:
                                resolved_path = path
                                break
                # Handle simple names
                else:
                    lookup_name = base_class_str
                    # Case 2: The base class is in the same file
                    if lookup_name in local_class_names:
                        resolved_path = caller_file_path
                    # Case 3: The base class was imported directly (e.g., from module import Parent)
                    elif lookup_name in local_imports:
                        full_import_name = local_imports[lookup_name]
                        possible_paths = imports_map.get(target_class_name, [])
                        for path in possible_paths:
                            if full_import_name.replace('.', '/') in path:
                                resolved_path = path
                                break
                    # Case 4: Fallback to global map (less reliable)
                    elif lookup_name in imports_map:
                        possible_paths = imports_map[lookup_name]
                        if len(possible_paths) == 1:
                            resolved_path = possible_paths[0]
                
                # If a path was found, create the relationship
                if resolved_path:
                    session.run("""
                        MATCH (child:Class {name: $child_name, path: $path})
                        MATCH (parent:Class {name: $parent_name, path: $resolved_parent_file_path})
                        MERGE (child)-[:INHERITS]->(parent)
                    """,
                    child_name=class_item['name'],
                    path=caller_file_path,
                    parent_name=target_class_name,
                    resolved_parent_file_path=resolved_path)


    def _create_csharp_inheritance_and_interfaces(self, session, file_data: Dict, imports_map: dict):
        """Create INHERITS and IMPLEMENTS relationships for C# types."""
        if file_data.get('lang') != 'c_sharp':
            return
            
        caller_file_path = str(Path(file_data['path']).resolve())
        
        # Collect all local type names
        local_type_names = set()
        for type_list in ['classes', 'interfaces', 'structs', 'records']:
            local_type_names.update(t['name'] for t in file_data.get(type_list, []))
        
        # Process all type declarations that can have bases
        for type_list_name, type_label in [('classes', 'Class'), ('structs', 'Struct'), ('records', 'Record'), ('interfaces', 'Interface')]:
            for type_item in file_data.get(type_list_name, []):
                if not type_item.get('bases'):
                    continue
                
                for base_str in type_item['bases']:
                    # Clean up the base name (remove generic parameters, etc.)
                    base_name = base_str.split('<')[0].strip()
                    
                    # Determine if this is an interface
                    is_interface = False
                    resolved_path = caller_file_path
                    
                    # Check if base is a local interface
                    for iface in file_data.get('interfaces', []):
                        if iface['name'] == base_name:
                            is_interface = True
                            break
                    
                    # Check if base is in imports_map
                    if base_name in imports_map:
                        possible_paths = imports_map[base_name]
                        if len(possible_paths) > 0:
                            resolved_path = possible_paths[0]
                    
                    # For C#, first base is usually the class (if any), rest are interfaces
                    base_index = type_item['bases'].index(base_str)
                    
                    # Try to determine if it's an interface
                    if is_interface or (base_index > 0 and type_label == 'Class'):
                        # This is an IMPLEMENTS relationship
                        session.run("""
                            MATCH (child {name: $child_name, path: $path})
                            WHERE child:Class OR child:Struct OR child:Record
                            MATCH (iface:Interface {name: $interface_name})
                            MERGE (child)-[:IMPLEMENTS]->(iface)
                        """,
                        child_name=type_item['name'],
                        path=caller_file_path,
                        interface_name=base_name)
                    else:
                        # This is an INHERITS relationship
                        session.run("""
                            MATCH (child {name: $child_name, path: $path})
                            WHERE child:Class OR child:Record OR child:Interface
                            MATCH (parent {name: $parent_name})
                            WHERE parent:Class OR parent:Record OR parent:Interface
                            MERGE (child)-[:INHERITS]->(parent)
                        """,
                        child_name=type_item['name'],
                        path=caller_file_path,
                        parent_name=base_name)

    def _create_all_inheritance_links(self, all_file_data: list[Dict], imports_map: dict, job_id: str = None):
        """Create INHERITS relationships for all classes after all files have been processed."""
        total = len(all_file_data)
        if job_id:
            self.job_manager.update_job(job_id, stage="inheritance", total_files=total, processed_files=0, current_file="")
        with self.driver.session() as session:
            for idx, file_data in enumerate(all_file_data):
                # Handle C# separately
                if file_data.get('lang') == 'c_sharp':
                    self._create_csharp_inheritance_and_interfaces(session, file_data, imports_map)
                else:
                    self._create_inheritance_links(session, file_data, imports_map)
                if job_id:
                    self.job_manager.update_job(job_id, processed_files=idx + 1)
                
    def delete_file_from_graph(self, path: str):
        """Deletes a file and all its contained elements and relationships."""
        file_path_str = str(Path(path).resolve())
        with self.driver.session() as session:
            parents_res = session.run("""
                MATCH (f:File {path: $path})<-[:CONTAINS*]-(d:Directory)
                RETURN d.path as path ORDER BY d.path DESC
            """, path=file_path_str)
            parent_paths = [record["path"] for record in parents_res]

            session.run(
                """
                MATCH (f:File {path: $path})
                OPTIONAL MATCH (f)-[:CONTAINS]->(element)
                DETACH DELETE f, element
                """,
                path=file_path_str,
            )
            info_logger(f"Deleted file and its elements from graph: {file_path_str}")

            for path in parent_paths:
                session.run("""
                    MATCH (d:Directory {path: $path})
                    WHERE NOT (d)-[:CONTAINS]->()
                    DETACH DELETE d
                """, path=path)

    def delete_repository_from_graph(self, repo_path: str) -> bool:
        """Deletes a repository and all its contents from the graph. Returns True if deleted, False if not found."""
        repo_path_str = str(Path(repo_path).resolve())
        with self.driver.session() as session:
            # Check if it exists
            result = session.run("MATCH (r:Repository {path: $path}) RETURN count(r) as cnt", path=repo_path_str).single()
            if not result or result["cnt"] == 0:
                warning_logger(f"Attempted to delete non-existent repository: {repo_path_str}")
                return False

            session.run("""MATCH (r:Repository {path: $path})
                          OPTIONAL MATCH (r)-[:CONTAINS*]->(e)
                          DETACH DELETE r, e""", path=repo_path_str)
            info_logger(f"Deleted repository and its contents from graph: {repo_path_str}")
            return True

    def update_file_in_graph(self, path: Path, repo_path: Path, imports_map: dict):
        """Updates a single file's nodes in the graph."""
        file_path_str = str(path.resolve())
        repo_name = repo_path.name
        
        self.delete_file_from_graph(file_path_str)

        if path.exists():
            file_data = self.parse_file(repo_path, path)
            
            if "error" not in file_data:
                self.add_file_to_graph(file_data, repo_name, imports_map)
                return file_data
            else:
                error_logger(f"Skipping graph add for {file_path_str} due to parsing error: {file_data['error']}")
                return None
        else:
            return {"deleted": True, "path": file_path_str}

    def parse_file(self, repo_path: Path, path: Path, is_dependency: bool = False) -> Dict:
        """Parses a file with the appropriate language parser and extracts code elements."""
        parser = self.parsers.get(path.suffix)
        if not parser:
            warning_logger(f"No parser found for file extension {path.suffix}. Skipping {path}")
            return {"path": str(path), "error": f"No parser for {path.suffix}"}

        debug_log(f"[parse_file] Starting parsing for: {path} with {parser.language_name} parser")
        try:
            index_source = (get_config_value("INDEX_SOURCE") or "false").lower() == "true"
            if parser.language_name == 'python':
                is_notebook = path.suffix == '.ipynb'
                file_data = parser.parse(
                    path,
                    is_dependency,
                    is_notebook=is_notebook,
                    index_source=index_source
                )
            else:
                file_data = parser.parse(
                    path,
                    is_dependency,
                    index_source=index_source
                )
            file_data['repo_path'] = str(repo_path)
            return file_data
        except Exception as e:
            error_logger(f"Error parsing {path} with {parser.language_name} parser: {e}")
            debug_log(f"[parse_file] Error parsing {path}: {e}")
            return {"path": str(path), "error": str(e)}

    def estimate_processing_time(self, path: Path) -> Optional[Tuple[int, float]]:
        """Estimate processing time and file count"""
        try:
            supported_extensions = self.parsers.keys()
            if path.is_file():
                if path.suffix in supported_extensions:
                    files = [path]
                else:
                    return 0, 0.0 # Not a supported file type
            else:
                all_files = path.rglob("*")
                files = [f for f in all_files if f.is_file() and f.suffix in supported_extensions]

                # Filter default ignored directories
                ignore_dirs_str = get_config_value("IGNORE_DIRS") or ""
                if ignore_dirs_str:
                    ignore_dirs = {d.strip().lower() for d in ignore_dirs_str.split(',') if d.strip()}
                    if ignore_dirs:
                        kept_files = []
                        for f in files:
                            try:
                                parts = set(p.lower() for p in f.relative_to(path).parent.parts)
                                if not parts.intersection(ignore_dirs):
                                    kept_files.append(f)
                            except ValueError:
                                kept_files.append(f)
                        files = kept_files
            
            total_files = len(files)
            estimated_time = total_files * 0.05 # tree-sitter is faster
            return total_files, estimated_time
        except Exception as e:
            error_logger(f"Could not estimate processing time for {path}: {e}")
            return None

    async def _build_graph_from_scip(
        self, path: Path, is_dependency: bool, job_id: Optional[str], lang: str
    ):
        """
        SCIP-based indexing path. Activated only when SCIP_INDEXER=true and
        a scip-<lang> binary is available.

        Steps:
          1. Run scip-<lang> CLI → index.scip
          2. Parse index.scip → nodes + reference edges
          3. Write nodes to graph (same MERGE queries as Tree-sitter path)
          4. Tree-sitter supplement: add source text + cyclomatic_complexity
          5. Write SCIP CALLS edges (precise, no heuristics)
        """
        import tempfile
        from .scip_indexer import ScipIndexer, ScipIndexParser
        from .graph_builder import TreeSitterParser  # supplement pass

        if job_id:
            self.job_manager.update_job(job_id, status=JobStatus.RUNNING)

        self.add_repository_to_graph(path, is_dependency)
        repo_name = path.name

        try:
            # Step 1: Run SCIP indexer
            with tempfile.TemporaryDirectory(prefix="cgc_scip_") as tmpdir:
                scip_file = ScipIndexer().run(path, lang, Path(tmpdir))

                if not scip_file:
                    warning_logger(
                        f"SCIP indexer produced no output for {path}. "
                        "Falling back to Tree-sitter."
                    )
                    # Hand off to Tree-sitter pipeline by re-calling without SCIP flag
                    # (the flag is checked at the start; override is not needed because
                    # we return here — caller will not re-enter this branch)
                    raise RuntimeError("SCIP produced no index — triggering Tree-sitter fallback")

                # Step 2: Parse index.scip
                scip_data = ScipIndexParser().parse(scip_file, path)
            
            if not scip_data:
                raise RuntimeError("SCIP parse returned empty result")

            files_data = scip_data.get("files", {})
            file_paths = [Path(p) for p in files_data.keys() if Path(p).exists()]
            
            # Step 3: Pre-scan for imports to correctly associate external modules/classes
            imports_map = self._pre_scan_for_imports(file_paths)

            if job_id:
                self.job_manager.update_job(job_id, total_files=len(files_data))

            # Step 4: Write nodes to graph using existing add_file_to_graph()
            processed = 0
            for abs_path_str, file_data in files_data.items():
                file_data["repo_path"] = str(path.resolve())
                if job_id:
                    self.job_manager.update_job(job_id, current_file=abs_path_str)

                # Step 5: Tree-sitter supplement — add source text, complexity, imports and bases
                file_path = Path(abs_path_str)
                if file_path.exists() and file_path.suffix in self.parsers:
                    try:
                        ts_parser = self.parsers[file_path.suffix]
                        ts_data = ts_parser.parse(file_path, is_dependency, index_source=True)
                        if "error" not in ts_data:
                            # 1. Functions: complexity, source, decorators
                            ts_funcs = {f["name"]: f for f in ts_data.get("functions", [])}
                            for f in file_data.get("functions", []):
                                ts_f = ts_funcs.get(f["name"])
                                if ts_f:
                                    f.update({
                                        "source": ts_f.get("source"),
                                        "cyclomatic_complexity": ts_f.get("cyclomatic_complexity", 1),
                                        "decorators": ts_f.get("decorators", [])
                                    })
                            
                            # 2. Classes: bases (inheritance)
                            ts_classes = {c["name"]: c for c in ts_data.get("classes", [])}
                            for c in file_data.get("classes", []):
                                ts_c = ts_classes.get(c["name"])
                                if ts_c:
                                    c["bases"] = ts_c.get("bases", [])
                            
                            # 3. Imports: critical for cross-file resolution
                            file_data["imports"] = ts_data.get("imports", [])
                            
                            # 4. Variables/Other: value, etc.
                            file_data["variables"] = ts_data.get("variables", [])
                    except Exception as e:
                        debug_log(f"Tree-sitter supplement failed for {abs_path_str}: {e}")

                self.add_file_to_graph(file_data, repo_name, imports_map)

                processed += 1
                if job_id:
                    self.job_manager.update_job(job_id, processed_files=processed)
                await asyncio.sleep(0.01)

            # Step 6: Create INHERITS relationships (Supplemented from Tree-sitter)
            self._create_all_inheritance_links(list(files_data.values()), imports_map)

            # Step 7: Write SCIP CALLS edges — precise cross-file resolution
            with self.driver.session() as session:
                for file_data in files_data.values():
                    for edge in file_data.get("function_calls_scip", []):
                        try:
                            # Use line numbers for precise matching in case of duplicates
                            session.run("""
                                MATCH (caller:Function {name: $caller_name, path: $caller_file, line_number: $caller_line})
                                MATCH (callee:Function {name: $callee_name, path: $callee_file, line_number: $callee_line})
                                MERGE (caller)-[:CALLS {line_number: $ref_line, source: 'scip'}]->(callee)
                            """,
                            caller_name=self._name_from_symbol(edge["caller_symbol"]),
                            caller_file=edge["caller_file"],
                            caller_line=edge["caller_line"],
                            callee_name=edge["callee_name"],
                            callee_file=edge["callee_file"],
                            callee_line=edge["callee_line"],
                            ref_line=edge["ref_line"],
                            )
                        except Exception:
                            pass  # best-effort: node might not be indexed yet

            if job_id:
                self.job_manager.update_job(job_id, status=JobStatus.COMPLETED, end_time=datetime.now())

        except RuntimeError as e:
            # Graceful fallback to Tree-sitter when SCIP fails
            warning_logger(f"SCIP path failed ({e}), re-running with Tree-sitter...")
            # Temporarily disable the flag in-memory so the recursive call goes straight to TS
            # (we do this by calling the internal Tree-sitter steps directly)
            if job_id:
                self.job_manager.update_job(job_id, status=JobStatus.RUNNING)
            # Re-enter the async flow without SCIP check — handled by caller returning early
            # For simplicity, we just let the exception propagate to the outer handler so the
            # job is marked FAILED with a meaningful message rather than silently degrading.
            raise

        except Exception as e:
            error_logger(f"SCIP indexing failed for {path}: {e}")
            if job_id:
                self.job_manager.update_job(
                    job_id, status=JobStatus.FAILED, end_time=datetime.now(), errors=[str(e)]
                )

    def _name_from_symbol(self, symbol: str) -> str:
        """Extract human-readable name from a SCIP symbol ID string."""
        import re
        s = symbol.rstrip(".#")
        s = re.sub(r"\(\)\.?$", "", s) # Remove trailing () or ().
        parts = re.split(r'[/#]', s)
        last = parts[-1] if parts else symbol
        return last or symbol


    async def build_graph_from_path_async(
        self, path: Path, is_dependency: bool = False, job_id: str = None
    ):
        """Builds graph from a directory or file path."""
        try:
            # ------------------------------------------------------------------
            # SCIP feature flag: SCIP_INDEXER=true in ~/.codegraphcontext/.env
            # When enabled (and the binary is installed), SCIP handles the
            # indexing for supported languages. SCIP_INDEXER=false (default)
            # means this entire block is a no-op and existing behaviour is kept.
            # ------------------------------------------------------------------
            scip_enabled = (get_config_value("SCIP_INDEXER") or "false").lower() == "true"
            if scip_enabled:
                from .scip_indexer import ScipIndexer, ScipIndexParser, detect_project_lang, is_scip_available
                scip_langs_str = get_config_value("SCIP_LANGUAGES") or "python,typescript,go,rust,java"
                scip_languages = [l.strip() for l in scip_langs_str.split(",") if l.strip()]
                detected_lang = detect_project_lang(path, scip_languages)

                if detected_lang and is_scip_available(detected_lang):
                    info_logger(f"SCIP_INDEXER=true — using SCIP for language: {detected_lang}")
                    await self._build_graph_from_scip(path, is_dependency, job_id, detected_lang)
                    return   # SCIP handled it; skip Tree-sitter pipeline below
                else:
                    if detected_lang:
                        warning_logger(
                            f"SCIP_INDEXER=true but scip-{detected_lang} binary not found. "
                            f"Falling back to Tree-sitter. Install it first."
                        )
                    else:
                        info_logger(
                            "SCIP_INDEXER=true but no SCIP-supported language detected. "
                            "Falling back to Tree-sitter."
                        )
            # ------------------------------------------------------------------
            # Existing Tree-sitter pipeline (unchanged)
            # ------------------------------------------------------------------
            if job_id:
                self.job_manager.update_job(job_id, status=JobStatus.RUNNING)
            
            self.add_repository_to_graph(path, is_dependency)
            repo_name = path.name

            # Search for .cgcignore upwards
            cgcignore_path = None
            ignore_root = path.resolve()
            
            # Start search from path (or parent if path is file)
            curr = path.resolve()
            if not curr.is_dir():
                curr = curr.parent

            # Walk up looking for .cgcignore
            while True:
                candidate = curr / ".cgcignore"
                if candidate.exists():
                    cgcignore_path = candidate
                    ignore_root = curr
                    debug_log(f"Found .cgcignore at {ignore_root}")
                    break
                if curr.parent == curr: # Root hit
                    break
                curr = curr.parent

            spec = None
            ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)
            if cgcignore_path:
                with open(cgcignore_path) as f:
                    user_patterns = [line.strip() for line in f.read().splitlines() if line.strip() and not line.strip().startswith('#')]
                ignore_patterns = DEFAULT_IGNORE_PATTERNS + user_patterns
            else:
                # No .cgcignore found — create one in the project root with default patterns
                # so the user can see and customize what's being ignored
                project_root = path.resolve() if path.is_dir() else path.resolve().parent
                new_cgcignore = project_root / ".cgcignore"
                try:
                    cgcignore_content = "# Auto-generated by CodeGraphContext\n"
                    cgcignore_content += "# Default ignore patterns for binary/media files\n"
                    cgcignore_content += "# Add your own patterns below\n\n"
                    cgcignore_content += "\n".join(DEFAULT_IGNORE_PATTERNS) + "\n"
                    new_cgcignore.write_text(cgcignore_content)
                    info_logger(f"Created default .cgcignore at {new_cgcignore}")
                except OSError as e:
                    warning_logger(f"Could not create .cgcignore at {new_cgcignore}: {e}")

            # Load .gitignore patterns if present (complements .cgcignore)
            project_root = path.resolve() if path.is_dir() else path.resolve().parent
            gitignore_path = project_root / ".gitignore"
            if gitignore_path.exists():
                try:
                    with open(gitignore_path) as f:
                        gitignore_patterns = [line.strip() for line in f.read().splitlines()
                                              if line.strip() and not line.strip().startswith('#')]
                    ignore_patterns = ignore_patterns + gitignore_patterns
                    info_logger(f"Loaded {len(gitignore_patterns)} patterns from .gitignore")
                except Exception as e:
                    warning_logger(f"Could not load .gitignore: {e}")

            spec = pathspec.PathSpec.from_lines('gitwildmatch', ignore_patterns)

            supported_extensions = self.parsers.keys()
            all_files = path.rglob("*") if path.is_dir() else [path]

            # Previously only files with supported extensions were indexed.
            # Updated to include all files so that unsupported file types
            # can still be represented as minimal File nodes in the graph.
            files = [f for f in all_files if f.is_file()]

            # Filter default ignored directories
            ignore_dirs_str = get_config_value("IGNORE_DIRS") or ""
            if ignore_dirs_str and path.is_dir():
                ignore_dirs = {d.strip().lower() for d in ignore_dirs_str.split(',') if d.strip()}
                if ignore_dirs:
                    kept_files = []
                    for f in files:
                        try:
                            # Check if any parent directory in the relative path is in ignore list
                            parts = set(p.lower() for p in f.relative_to(path).parent.parts)
                            if not parts.intersection(ignore_dirs):
                                kept_files.append(f)
                            else:
                                # debug_log(f"Skipping default ignored file: {f}")
                                pass
                        except ValueError:
                             kept_files.append(f)
                    files = kept_files
            
            # Enforce MAX_FILE_SIZE_MB
            max_file_size_mb = get_config_value("MAX_FILE_SIZE_MB")
            if max_file_size_mb and max_file_size_mb != "unlimited":
                try:
                    max_bytes = float(max_file_size_mb) * 1024 * 1024
                    before_count = len(files)
                    files = [f for f in files if f.stat().st_size <= max_bytes]
                    skipped = before_count - len(files)
                    if skipped > 0:
                        info_logger(f"Skipped {skipped} files exceeding {max_file_size_mb}MB")
                except (ValueError, OSError) as e:
                    warning_logger(f"Could not apply MAX_FILE_SIZE_MB filter: {e}")

            # Enforce IGNORE_TEST_FILES
            ignore_tests = (get_config_value("IGNORE_TEST_FILES") or "false").lower() == "true"
            if ignore_tests and path.is_dir():
                test_dir_names = {"test", "tests", "spec", "__tests__", "testing"}
                before_count = len(files)
                kept = []
                for f in files:
                    try:
                        parts = set(p.lower() for p in f.relative_to(path).parts)
                        if not parts.intersection(test_dir_names):
                            kept.append(f)
                    except ValueError:
                        kept.append(f)
                files = kept
                skipped = before_count - len(files)
                if skipped > 0:
                    info_logger(f"Skipped {skipped} test files (IGNORE_TEST_FILES=true)")

            # Enforce MAX_DEPTH
            max_depth = get_config_value("MAX_DEPTH")
            if max_depth and max_depth != "unlimited" and path.is_dir():
                try:
                    max_d = int(max_depth)
                    before_count = len(files)
                    files = [f for f in files if len(f.relative_to(path).parts) <= max_d]
                    skipped = before_count - len(files)
                    if skipped > 0:
                        info_logger(f"Skipped {skipped} files beyond depth {max_d}")
                except (ValueError, OSError) as e:
                    warning_logger(f"Could not apply MAX_DEPTH filter: {e}")

            if spec:
                filtered_files = []
                for f in files:
                    try:
                        # Match relative to the directory containing .cgcignore
                        rel_path = f.relative_to(ignore_root)
                        if not spec.match_file(str(rel_path)):
                            filtered_files.append(f)
                        else:
                            debug_log(f"Ignored file based on .cgcignore: {rel_path}")
                    except ValueError:
                        # Should not happen if ignore_root is a parent, but safety fallback
                        filtered_files.append(f)
                files = filtered_files
            if job_id:
                self.job_manager.update_job(job_id, total_files=len(files))
            
            # --- #5: Incremental indexing — detect changed files ---
            use_cache = (get_config_value("PARSE_CACHE_ENABLED") or "false").lower() == "true"
            repo_key = str(path.resolve())
            index_meta = self._load_index_meta() if use_cache else {}
            repo_meta = index_meta.get(repo_key, {})

            # Check if this repo already has data in DB; if not (e.g. --force wiped it),
            # ignore stale meta and do full index
            repo_exists_in_db = False
            if use_cache and repo_meta:
                try:
                    with self.driver.session() as session:
                        r = session.run("MATCH (f:File) WHERE f.path STARTS WITH $p RETURN count(f) AS c",
                                        p=repo_key).single()
                        repo_exists_in_db = r is not None and r['c'] > 0
                except Exception:
                    pass
                if not repo_exists_in_db:
                    info_logger("DB has no data for this repo — ignoring stale cache meta, doing full index")
                    repo_meta = {}

            changed_files = []
            unchanged_files = []
            for f in files:
                if not f.is_file():
                    continue
                fp = self._file_fingerprint(f)
                cached_fp = repo_meta.get(str(f.resolve()))
                if use_cache and repo_exists_in_db and cached_fp == fp:
                    unchanged_files.append(f)
                else:
                    changed_files.append(f)

            if use_cache and unchanged_files:
                info_logger(f"Incremental: {len(unchanged_files)} unchanged, {len(changed_files)} to process")
                files_to_process = changed_files
            else:
                files_to_process = files

            # --- #6: Use CREATE instead of MERGE for first-time index ---
            first_index = self._is_db_empty()
            if first_index:
                info_logger("First-time index detected — using CREATE for faster writes")

            # --- Single-pass parsing with #8 parse cache ---
            debug_log("Starting single-pass parsing...")
            all_file_data = []
            minimal_file_nodes = []
            processed_count = 0
            new_meta = dict(repo_meta)  # copy existing fingerprints

            for file in files_to_process:
                if file.is_file():
                    if job_id:
                        self.job_manager.update_job(job_id, current_file=str(file))
                    repo_path = path.resolve() if path.is_dir() else file.parent.resolve()

                    # #8: Try parse cache first
                    file_data = None
                    if use_cache:
                        file_data = self._load_cached_parse(file)
                        if file_data:
                            debug_log(f"Cache hit: {file}")

                    if file_data is None:
                        file_data = self.parse_file(repo_path, file, is_dependency)
                        if use_cache and "error" not in file_data:
                            self._save_parse_cache(file, file_data)

                    if "error" not in file_data:
                        all_file_data.append(file_data)
                    else:
                        minimal_file_nodes.append((file, repo_path))

                    # Update fingerprint
                    try:
                        new_meta[str(file.resolve())] = self._file_fingerprint(file)
                    except OSError:
                        pass

                    processed_count += 1
                    if job_id:
                        self.job_manager.update_job(job_id, processed_files=processed_count)
                    await asyncio.sleep(0.01)

            debug_log(f"Parsed {len(all_file_data)} files. Building imports map...")

            # Build imports_map from parsed data (replaces _pre_scan_for_imports)
            imports_map = {}
            for fd in all_file_data:
                file_path_str = str(Path(fd['path']).resolve())
                for func in fd.get('functions', []):
                    name = func['name']
                    if name not in imports_map:
                        imports_map[name] = []
                    imports_map[name].append(file_path_str)
                for cls in fd.get('classes', []):
                    name = cls['name']
                    if name not in imports_map:
                        imports_map[name] = []
                    imports_map[name].append(file_path_str)
                for iface in fd.get('interfaces', []):
                    name = iface['name']
                    if name not in imports_map:
                        imports_map[name] = []
                    imports_map[name].append(file_path_str)
                for trait in fd.get('traits', []):
                    name = trait['name']
                    if name not in imports_map:
                        imports_map[name] = []
                    imports_map[name].append(file_path_str)

            debug_log(f"Imports map built with {len(imports_map)} definitions. Writing to graph...")

            # Write all parsed files to graph
            for file_data in all_file_data:
                self.add_file_to_graph(file_data, repo_name, imports_map, use_create=first_index)

            # Write minimal nodes for unsupported files
            for file, repo_p in minimal_file_nodes:
                self.add_minimal_file_node(file, repo_p, is_dependency)

            self._create_all_inheritance_links(all_file_data, imports_map, job_id=job_id)

            # --- #7: Skip function calls if configured ---
            skip_calls = (get_config_value("SKIP_FUNCTION_CALLS") or "false").lower() == "true"
            if skip_calls:
                info_logger("SKIP_FUNCTION_CALLS=true — skipping function call relationship creation")
            else:
                self._create_all_function_calls(all_file_data, imports_map, job_id=job_id)

            # --- #5: Save index metadata ---
            if use_cache:
                index_meta[repo_key] = new_meta
                self._save_index_meta(index_meta)
            
            if job_id:
                self.job_manager.update_job(job_id, status=JobStatus.COMPLETED, end_time=datetime.now())
        except Exception as e:
            error_message=str(e)
            error_logger(f"Failed to build graph for path {path}: {error_message}")
            if job_id:
                '''checking if the repo got deleted '''
                if "no such file found" in error_message or "deleted" in error_message or "not found" in error_message:
                    status=JobStatus.CANCELLED
                    
                else:
                    status=JobStatus.FAILED

                self.job_manager.update_job(
                    job_id, status=status, end_time=datetime.now(), errors=[str(e)]
                )

    # Create a minimal File node for unsupported file types.
    # These files do not contain parsed entities but should still
    # appear in the repository graph as requested in issue #707.
    def add_minimal_file_node(self, file_path: Path, repo_path: Path, is_dependency: bool = False):

        file_path_str = str(file_path.resolve())
        file_name = file_path.name
        repo_name = repo_path.name
        repo_path_str = str(repo_path.resolve())

        with self.driver.session() as session:

            session.run(
                """
                MERGE (r:Repository {path: $repo_path})
                SET r.name = $repo_name
                """,
                repo_path=repo_path_str,
                repo_name=repo_name
            )

            session.run(
                """
                MERGE (f:File {path: $file_path})
                SET f.name = $file_name,
                    f.is_dependency = $is_dependency
                """,
                file_path=file_path_str,
                file_name=file_name,
                is_dependency=is_dependency
            )

            # Establish directory structure
            file_path_obj = Path(file_path_str)
            repo_path_obj = Path(repo_path_str)
            try:
                relative_path_to_file = file_path_obj.relative_to(repo_path_obj)
            except ValueError:
                # Fallback if not relative
                relative_path_to_file = Path(file_path_obj.name)
            
            parent_path = repo_path_str
            parent_label = 'Repository'

            for part in relative_path_to_file.parts[:-1]:
                current_path = Path(parent_path) / part
                current_path_str = str(current_path)
                
                session.run(f"""
                    MATCH (p:{parent_label} {{path: $parent_path}})
                    MERGE (d:Directory {{path: $current_path}})
                    SET d.name = $part
                    MERGE (p)-[:CONTAINS]->(d)
                """, parent_path=parent_path, current_path=current_path_str, part=part)

                parent_path = current_path_str
                parent_label = 'Directory'

            session.run(f"""
                MATCH (p:{parent_label} {{path: $parent_path}})
                MATCH (f:File {{path: $file_path}})
                MERGE (p)-[:CONTAINS]->(f)
            """, parent_path=parent_path, file_path=file_path_str)
