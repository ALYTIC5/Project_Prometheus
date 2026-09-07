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
        "activates_on": ["benchmark"],
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
        "activates_on": ["benchmark"],
        "agent_roles": [],
        "description": "Buy-and-hold benchmark — the first thing you beat",
        "kind": "monument",
    },
}

BUILDING_LOCATIONS: dict[str, dict[str, float]] = {
    "library": {"x": 1, "y": 2, "width": 3, "height": 2},
    "forge": {"x": 5, "y": 2, "width": 3, "height": 2},
    "oracle": {"x": 9, "y": 2, "width": 3, "height": 2},
    "arena": {"x": 1, "y": 5, "width": 3, "height": 2},
    "vault": {"x": 5, "y": 5, "width": 2, "height": 2},
    "treasury": {"x": 8, "y": 5, "width": 3, "height": 2},
    "harbour": {"x": 12, "y": 2, "width": 3, "height": 2},
    "archive": {"x": 12, "y": 5, "width": 2, "height": 2},
    "underworld": {"x": 12, "y": 8, "width": 2, "height": 2},
    "watchtower": {"x": 1, "y": 8, "width": 2, "height": 2},
    "temple": {"x": 5, "y": 8, "width": 3, "height": 2},
    "monument": {"x": 4, "y": 3.5, "width": 2, "height": 2},
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
