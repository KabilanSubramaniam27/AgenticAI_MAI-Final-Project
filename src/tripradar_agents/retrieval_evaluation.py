"""Deterministic retrieval metrics over independently reviewed evidence groups."""


def retrieval_metrics(retrieved, groups, relevant_passages, k=5, witness=None):
    if k < 1 or len(groups) > k:
        raise ValueError("Gold evidence groups must fit the declared retrieval capacity")
    if any(not members for members in groups.values()):
        raise ValueError("Each required group needs reviewed passages")
    if groups and (
        not witness
        or len(set(witness)) > k
        or any(not set(witness) & set(members) for members in groups.values())
    ):
        raise ValueError("Provide a reviewed <=k passage witness covering every required group")
    top = list(dict.fromkeys(retrieved))[:k]
    relevant = set(relevant_passages)
    if any(not set(members) <= relevant for members in groups.values()):
        raise ValueError("Group passages need positive relevance labels")
    satisfied = sum(bool(set(top) & set(members)) for members in groups.values())
    return {
        "k": k,
        "retrieved_count": len(top),
        "precision_at_k": len(set(top) & relevant) / k,
        "evidence_group_recall_at_k": satisfied / len(groups) if groups else None,
        "passage_recall_at_k": len(set(top) & relevant) / len(relevant) if relevant else None,
        "correct_abstention": not top if not groups and not relevant else None,
    }
