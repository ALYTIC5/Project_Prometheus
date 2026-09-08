"""Construction manifest — maps each building to its prompt, activation tables, and agent roles.

This IS the documentation of what each prompt will build. The frontend reads
it to show "Coming in Prompt N" tooltips on scaffolded buildings.

This module is the canonical home of the manifest, the world layout and the
building colours. `world/projection.py` imports from here, not the reverse —
the projection depends on the manifest, the manifest depends on nothing.
"""

from __future__ import annotations

from typing import Any

CONSTRUCTION_MANIFEST: dict[str, dict[str, Any]] = {
    "library": {
        "prompt": 2,
        "activates_on": ["ohlcv_bars"],
        "agent_roles": ["scribe"],
        "description": "Research data ingestion",
        "kind": "library",
    },
    "forge": {
        "prompt": 4,
        "activates_on": ["strategies"],
        "agent_roles": ["engineer"],
        "description": "Strategy generation and backtest engine",
        "kind": "forge",
    },
    "oracle": {
        "prompt": 5,
        "activates_on": ["validation_results"],
        "agent_roles": ["statistician"],
        "description": "Validation and falsification",
        "kind": "oracle",
    },
    "arena": {
        "prompt": 4,
        "activates_on": ["experiments"],
        "agent_roles": ["experimenter"],
        "description": "Comparative experiments",
        "kind": "arena",
    },
    "vault": {
        "prompt": 5,
        "activates_on": ["holdout"],
        "agent_roles": ["guardian"],
        "description": "Holdout — sacred, sealed from day one",
        "kind": "vault",
    },
    "treasury": {
        "prompt": 2,
        "activates_on": ["benchmark_equity"],
        "agent_roles": ["guardian"],
        "description": "Portfolio treasury and benchmark",
        "kind": "treasury",
    },
    "harbour": {
        "prompt": 8,
        "activates_on": ["paper_trades"],
        "agent_roles": ["builder"],
        "description": "Paper trading",
        "kind": "harbour",
    },
    "archive": {
        "prompt": 4,
        "activates_on": ["results"],
        "agent_roles": ["auditor"],
        "description": "Retired strategies",
        "kind": "archive",
    },
    "underworld": {
        "prompt": 4,
        "activates_on": ["decisions"],
        "agent_roles": ["guardian"],
        "description": "Rejected strategies",
        "kind": "underworld",
    },
    "watchtower": {
        "prompt": 1,
        "activates_on": ["health"],
        "agent_roles": ["guardian"],
        "description": "Alerts and monitoring",
        "kind": "watchtower",
    },
    "temple": {
        "prompt": 6,
        "activates_on": ["ablation"],
        "agent_roles": ["scholar"],
        "description": "Meta-learning and component registry",
        "kind": "temple",
    },
    "monument": {
        "prompt": 1,
        "activates_on": ["benchmark_equity"],
        "agent_roles": [],
        "description": "Buy-and-hold benchmark — the first thing you beat",
        "kind": "monument",
    },
}

MONUMENT_CLEAR_RADIUS = 2

# City layout, hand-authored on a 26x26 tile grid. Footprint size class is
# implied by width/height (1x1 = TOWER, 2x2 = MEDIUM, 3x3 = LARGE) rather
# than tracked as a separate field -- one source of truth per building.
# Placement rules (enforced by tests/test_building_layout.py):
#   - zero pairwise footprint overlap
#   - >=1 empty tile between every pair of footprints
#   - nothing else inside the monument's MONUMENT_CLEAR_RADIUS-tile box --
#     it is the city's visual anchor and must never be occluded
#   - vault sits one tile from oracle (validation guards the holdout) but
#     in its own isolated footprint, not merged into the oracle block
#   - underworld sits alone in the low-right corner, away from every
#     other cluster
#   - harbour sits near the low-x map edge; columns x<2 are reserved as
#     water in the frontend's ground renderer
BUILDING_LOCATIONS: dict[str, dict[str, float]] = {
    "monument": {"x": 13, "y": 13, "width": 1, "height": 1},
    "watchtower": {"x": 13, "y": 4, "width": 1, "height": 1},
    "forge": {"x": 2, "y": 4, "width": 3, "height": 3},
    "oracle": {"x": 18, "y": 10, "width": 3, "height": 3},
    "arena": {"x": 4, "y": 18, "width": 3, "height": 3},
    "treasury": {"x": 18, "y": 4, "width": 3, "height": 3},
    "vault": {"x": 18, "y": 14, "width": 2, "height": 2},
    "underworld": {"x": 22, "y": 22, "width": 2, "height": 2},
    "harbour": {"x": 2, "y": 13, "width": 2, "height": 2},
    "library": {"x": 3, "y": 10, "width": 2, "height": 2},
    "archive": {"x": 22, "y": 4, "width": 2, "height": 2},
    "temple": {"x": 8, "y": 18, "width": 2, "height": 2},
}

BUILDING_COLORS: dict[str, str] = {
    "library": "#4A90D9",
    "forge": "#E67E22",
    "oracle": "#8E44AD",
    "arena": "#F1C40F",
    "vault": "#7F8C8D",
    "treasury": "#27AE60",
    "harbour": "#3498DB",
    "archive": "#95A5A6",
    "underworld": "#2C3E50",
    "watchtower": "#E74C3C",
    "temple": "#D4A574",
    "monument": "#F39C12",
}

ALL_BUILDINGS = list(CONSTRUCTION_MANIFEST.keys())

BUILDING_ORDER = [
    "monument",
    "watchtower",
    "library",
    "treasury",
    "forge",
    "oracle",
    "arena",
    "vault",
    "archive",
    "harbour",
    "underworld",
    "temple",
]

ROLE_COLORS: dict[str, str] = {
    "builder": "#F39C12",
    "scribe": "#3498DB",
    "engineer": "#E67E22",
    "experimenter": "#F1C40F",
    "statistician": "#8E44AD",
    "guardian": "#E74C3C",
    "auditor": "#95A5A6",
    "necromancer": "#8B0000",
    "scholar": "#D4A574",
    "prophet": "#9B59B6",
}

ROLE_ICONS: dict[str, str] = {
    "builder": "🔨",
    "scribe": "📜",
    "engineer": "⚙️",
    "experimenter": "🧪",
    "statistician": "📊",
    "guardian": "🛡️",
    "auditor": "🔍",
    "necromancer": "💀",
    "scholar": "📚",
    "prophet": "🔮",
}


def get_buildings_by_prompt(prompt: int) -> list[str]:
    return [
        bid for bid, manifest in CONSTRUCTION_MANIFEST.items() if manifest.get("prompt") == prompt
    ]


def get_building_info(building_id: str) -> dict[str, Any]:
    manifest = CONSTRUCTION_MANIFEST.get(building_id, {})
    loc = BUILDING_LOCATIONS.get(building_id, {})
    return {
        "id": building_id,
        "kind": manifest.get("kind", building_id),
        "description": manifest.get("description", ""),
        "prompt": manifest.get("prompt"),
        "activates_on": manifest.get("activates_on", []),
        "agent_roles": manifest.get("agent_roles", []),
        "location": loc,
        "color": BUILDING_COLORS.get(building_id, "#CCCCCC"),
    }


def get_phase_description(phase_name: str) -> str:
    descriptions = {
        "PLANNED": "Planned for future prompt — grey silhouette",
        "SCAFFOLDING": "Under construction — wireframe with builders working",
        "FOUNDATION": "Base visible, walls going up",
        "ACTIVE": "Fully built, operational, lit",
        "DAMAGED": "Cracks, sparks, warning lights",
        "SEALED": "Chains, locks — sacred/inaccessible",
        "OVERGROWN": "Vines, dust — dormant/abandoned",
    }
    return descriptions.get(phase_name, "Unknown phase")
