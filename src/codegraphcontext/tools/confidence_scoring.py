"""
Confidence scoring for CALLS relationships.
Maps resolution methods to confidence values.
"""

CONFIDENCE_SCORES = {
    # Precise matches
    'receiver_type_exact':      0.95,
    'receiver_type_inherited':  0.85,
    'context_type_exact':       0.85,
    'same_file_unique':         0.85,
    # Inferred matches
    'overload_by_arg_count':    0.80,
    'overload_by_arg_type':     0.75,
    'imports_map_unique':       0.75,
    'interface_to_impl':        0.70,
    'inherits_chain_found':     0.70,
    # Fuzzy matches
    'imports_map_first':        0.50,
    'name_match_cross_file':    0.40,
    'fallback_repo_scope':      0.30,
    # Multi-candidate
    'multi_candidate':          0.20,
    'fallback_multi':           0.10,
}

def get_confidence(resolved_by: str) -> float:
    return CONFIDENCE_SCORES.get(resolved_by, 0.50)
