"""Anti-gaming penalties — Sprint 3.

Five layers:

- ``vcs.py``: Vote Correlation Score — detects coordinated upreping rings.
- ``clustering.py``: clustering coefficient — detects sophisticated farming
  where voters also uprep each other.
- ``temporal.py``: burst detection — flags suspicious uprep storms.
- ``farming.py``: easy-bet detection — penalizes "predictors" who only
  bet on near-certain outcomes.
- ``progressive_penalty.py``: whale deterrence — gaming penalties scale
  with the violator's oracle rep so high-rep nodes can't shrug them off.

All five are pure functions over the chain. They run as deterministic
chain analysis (every node computes the same scores from the same chain
history), matching IMPLEMENTATION_PLAN.md §3.3.

Cross-cutting design rule: anti-gaming reads happen in the background.
A user who is being legitimately upreped does not block the UI on
penalty recomputation; the computed common-rep view simply uses the
last cached value and refreshes asynchronously.
"""

from services.infonet.reputation.anti_gaming.clustering import (
    clustering_penalty,
    compute_clustering_coefficient,
)
from services.infonet.reputation.anti_gaming.farming import (
    compute_farming_pct,
    farming_multiplier,
)
from services.infonet.reputation.anti_gaming.progressive_penalty import (
    apply_progressive_penalty,
    compute_rep_multiplier,
)
from services.infonet.reputation.anti_gaming.temporal import (
    is_in_burst,
    temporal_multiplier,
)
from services.infonet.reputation.anti_gaming.vcs import compute_vcs

__all__ = [
    "apply_progressive_penalty",
    "clustering_penalty",
    "compute_clustering_coefficient",
    "compute_farming_pct",
    "compute_rep_multiplier",
    "compute_vcs",
    "farming_multiplier",
    "is_in_burst",
    "temporal_multiplier",
]
