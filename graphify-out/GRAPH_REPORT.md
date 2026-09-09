# Graph Report - .  (2026-09-09)

## Corpus Check
- 160 files · ~260,961 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 760 nodes · 1205 edges · 105 communities (59 shown, 46 thin omitted)
- Extraction: 97% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 29 edges (avg confidence: 0.76)
- Token cost: 0 input · 1,449,924 output

## Community Hubs (Navigation)
- Isometric Skills Repo Overview
- Data Ingestion & Versioning
- Project Constitution & Dependencies
- Core DB Schema & Survivorship
- Risk & Research Policy Config
- The Laws & Point-in-Time Plan
- Asset Generation Pipeline
- No-Real-Money & Policy Isolation
- Frontend Package Manifest
- Data Quality Checks
- World State Entities
- Iso.js Rendering Engine
- Point-in-Time Schema & Lookahead Test
- Frontend World View & API
- Building Sprites & Registry
- Scoreboard & World API Routes
- Frontend TypeScript Config
- Frontend Isometric Projection & Monument
- App Entrypoint & Static Serving
- Frontend Type Definitions
- Buildings API & World Broadcast
- Builder Agent Rendering
- World Construction & Drilldown
- Append-Only History Tests
- Social Preview Card Content
- Health Check API
- Ground & Road Rendering
- Sprite Color Palette
- Iso Engine Package Manifest
- Construction Phase Determination
- Building Layout Tests
- Terrain Tile Set Assets
- AgentQuant & Temple Prompts
- World Enums
- Paper-Only Law & Qubx Eval
- Sample Map Rendering Assets
- Next.js Root Layout
- Next.js Home Page
- Depth-Sorting Diagram Panels
- Terrain Tiling Comparison
- Holdout Sacred Test
- Global Threshold Test
- Cost Discipline Note
- Deterministic Core Principle
- Pin Everything Principle
- Next.js Config
- Watchtower Building Prompt
- Stratevo Evaluation Prompt
- Test Fixtures (conftest)
- Project Identity Node
- asyncpg Dependency
- httpx Dependency
- mypy Dependency
- pre-commit Dependency
- psycopg Dependency
- pytest Dependency
- pytest-asyncio Dependency
- pyyaml Dependency
- react Dependency
- ruff Dependency
- sqlalchemy Dependency
- types-pyyaml Dependency
- typescript Dependency
- Experiment ID Counter (Plan)
- Strategy ID Counter (Plan)
- Data Layer Models (Plan)
- Data Quality (Plan)
- Demo Animation Asset
- Hero Banner Image
- Code of Conduct
- Sample Map Asset
- GitHub Funding Config
- Security Policy
- Animated Sprite Demo Image
- Python Package Manifest
- Prompt 11 Node
- Autotiling Demo Image
- Depth-Sorting Diagram
- Building Sprites Demo Image
- Character Sprites Demo Image
- Grid Math Diagram
- Object Sprites Demo Image
- Terrain Goal Map Image
- Single Grass Tile Image

## God Nodes (most connected - your core abstractions)
1. `Project README` - 39 edges
2. `Build-a-Game Capstone Walkthrough` - 24 edges
3. `run_quality_checks()` - 18 edges
4. `build_world_state()` - 17 edges
5. `Using Isometric Skills (Router)` - 16 edges
6. `gridToScreen()` - 15 edges
7. `compilerOptions` - 15 edges
8. `Isometric Renderer Live Demo` - 15 edges
9. `drawBuilding()` - 14 edges
10. `get_session_factory()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `Falsification before generation` --semantically_similar_to--> `The construction metaphor (the world never lies)`  [INFERRED] [semantically similar]
  CLAUDE.md → PROMPTS.md
- `Deterministic core (seed, code_sha, config_hash, data_version)` --semantically_similar_to--> `data/versioning.py data_version recording`  [INFERRED] [semantically similar]
  CLAUDE.md → docs/superpowers/plans/2026-09-06-point-in-time-data-layer.md
- `Point-in-Time Data Layer Implementation Plan` --implements--> `PROMPT 2 — Point-in-time data layer (Library rises)`  [AMBIGUOUS]
  docs/superpowers/plans/2026-09-06-point-in-time-data-layer.md → PROMPTS.md
- `Repo layout (prometheus/ package diagram)` --conceptually_related_to--> `Flat layout vs. CLAUDE.md's nested prometheus/ layout — flagged uncertainty`  [AMBIGUOUS]
  CLAUDE.md → docs/superpowers/plans/2026-09-04-repo-init-and-laws.md
- `Isometric Renderer Live Demo` --implements--> `gridToScreen()`  [EXTRACTED]
  isometric-game-skills-master/isometric-game-skills-master/demo/index.html → isometric-game-skills-master/isometric-game-skills-master/engine/iso.js

## Import Cycles
- 1-file cycle: `frontend/src/sprites/palette.ts -> frontend/src/sprites/palette.ts`

## Hyperedges (group relationships)
- **Law enforcement gate across CI, migration trigger, and law tests** — github_workflows_ci_laws_job, docs_superpowers_plans_2026_09_04_repo_init_and_laws_prevent_history_mutation_trigger, claude_tests_laws, claude_law_6_history_append_only [INFERRED 0.85]
- **The construction-metaphor world-state pipeline** — prompts_worldstate_schema, prompts_construction_manifest, docs_world_mapping_worldstate_fields, claude_world_view_is_projection [EXTRACTED 0.90]
- **Point-in-time data layer implementing Laws 1 and 2** — docs_superpowers_plans_2026_09_06_point_in_time_data_layer_pointintimeframe, docs_superpowers_plans_2026_09_06_point_in_time_data_layer_universe, claude_law_1_no_lookahead, claude_law_2_no_survivorship_bias, config_universe_symbols [EXTRACTED 0.90]
- **Skill Anatomy Enforced Across Contribution Surfaces** — isometric_game_skills_master_isometric_game_skills_master_docs_skill_anatomy_skill_anatomy_template, isometric_game_skills_master_isometric_game_skills_master_contributing_contributing_guide, isometric_game_skills_master_isometric_game_skills_master_github_pull_request_template_pr_template, isometric_game_skills_master_isometric_game_skills_master_github_issue_template_new_skill_new_skill_template [INFERRED 0.85]
- **Proof Layer: Goal Verified by CI, Demo, and Capstone** — isometric_game_skills_master_isometric_game_skills_master_goal_definition_of_done, isometric_game_skills_master_isometric_game_skills_master_github_workflows_validate_validate_workflow, isometric_game_skills_master_isometric_game_skills_master_scripts_validate_skills_validator_script, isometric_game_skills_master_isometric_game_skills_master_demo_index_isometric_renderer_demo, isometric_game_skills_master_isometric_game_skills_master_docs_build_a_game_build_a_game_walkthrough [INFERRED 0.85]
- **Live Demo Directly Exercises Six Engine/Camera Skills** — isometric_game_skills_master_isometric_game_skills_master_demo_index_isometric_renderer_demo, isometric_game_skills_master_isometric_game_skills_master_skills_isometric_grid_math_skill_skill, isometric_game_skills_master_isometric_game_skills_master_skills_canvas2d_isometric_renderer_skill_skill, isometric_game_skills_master_isometric_game_skills_master_skills_depth_sorting_occlusion_skill_skill, isometric_game_skills_master_isometric_game_skills_master_skills_tilemap_data_format_skill_skill, isometric_game_skills_master_isometric_game_skills_master_skills_tile_picking_interaction_skill_skill, isometric_game_skills_master_isometric_game_skills_master_skills_camera_pan_zoom_controls_skill_skill [EXTRACTED 1.00]
- **The Isometric Rendering Pipeline** — skills_isometric_grid_math_skill, skills_canvas2d_isometric_renderer_skill, skills_depth_sorting_occlusion_skill, skills_spritesheet_atlas_packing_skill, skills_tile_picking_interaction_skill, skills_canvas_performance_optimization_skill [INFERRED 0.85]
- **Isometric Asset Generation Pipeline** — skills_isometric_art_direction_skill, skills_isometric_object_sprites_skill, skills_isometric_building_sprites_skill, skills_isometric_character_sprites_skill, skills_transparent_cutout_cleanup_skill [INFERRED 0.85]
- **Seamless Terrain ComfyUI Workflow** — skills_seamless_isometric_terrain_skill, skills_seamless_isometric_terrain_references_02_production_guide, skills_seamless_isometric_terrain_references_03_prompts, skills_seamless_isometric_terrain_scripts_readme, skills_comfyui_lowvram_setup_skill [INFERRED 0.85]

## Communities (105 total, 46 thin omitted)

### Community 0 - "Isometric Skills Repo Overview"
Cohesion: 0.12
Nodes (46): Hero Banner Image, CHANGELOG v1.0.0 Release Notes, Contributing Guide, Isometric Renderer Live Demo, Demo README, Build-a-Game Capstone Walkthrough, Cursor Setup Guide, Getting Started Guide (+38 more)

### Community 1 - "Data Ingestion & Versioning"
Cohesion: 0.08
Nodes (39): Namespace, get_session(), AsyncSession, backfill(), ccxt_rows_to_bars(), ExchangeClient, ingest_symbol(), _load_bars_for_versioning() (+31 more)

### Community 2 - "Project Constitution & Dependencies"
Cohesion: 0.06
Nodes (39): Falsification before generation, Law 3: The holdout is sacred, Law 7: Thresholds change globally or not at all, Law 8: Everything runs against Buy & Hold, Stack (Python/FastAPI/SQLAlchemy/Polars/Postgres+TimescaleDB/PixiJS/Recharts), The world view is a projection (world/projection.py pure function), fastapi 0.115.0, Isometric math attribution (0xheycat/isometric-game-skills, MIT, algorithms only) (+31 more)

### Community 3 - "Core DB Schema & Survivorship"
Cohesion: 0.08
Nodes (32): Alembic runs synchronously (psycopg), even though the app runtime is async (asyn, run_migrations_offline(), run_migrations_online(), _sync_database_url(), async_sessionmaker, AsyncEngine, DeclarativeBase, Exception (+24 more)

### Community 4 - "Risk & Research Policy Config"
Cohesion: 0.10
Nodes (30): BaseSettings, MonkeyPatch, _content_hash(), load_research_policy(), AsyncSession, BaseModel, Path, Two config classes, deliberately kept apart.  RiskLimits: env-only, frozen, cons (+22 more)

### Community 5 - "The Laws & Point-in-Time Plan"
Cohesion: 0.06
Nodes (37): Don't invent numeric thresholds — ask instead, Law 1: No look-ahead, Law 2: No survivorship bias, Law 4: Risk limits are outside the loop, Law 6: History is append-only, No new dependency without justification, Repo layout (prometheus/ package diagram), tests/laws/ — the immutable law tests (+29 more)

### Community 6 - "Asset Generation Pipeline"
Cohesion: 0.15
Nodes (31): Phase 0 · Setup, Phase 1 · Generate art, Phase 2 · Process, Phase 3 · Engine, Phase 4 · Interaction, Phase 5 · Ship, Isometric Game Skills — the full pipeline, Canvas2D Isometric Renderer (+23 more)

### Community 7 - "No-Real-Money & Policy Isolation"
Cohesion: 0.12
Nodes (23): AST, Call, _assigned_names(), _assigned_value(), _called_name(), _parse(), expr, Module (+15 more)

### Community 8 - "Frontend Package Manifest"
Cohesion: 0.09
Nodes (22): dependencies, next, pixi.js, react, react-dom, recharts, devDependencies, @types/node (+14 more)

### Community 9 - "Data Quality Checks"
Cohesion: 0.19
Nodes (20): check_duplicate_timestamps(), check_gaps(), check_ohlc_relationships(), check_price_validity(), check_stale_bars(), check_volume_spikes(), _expected_bar_hours(), DataFrame (+12 more)

### Community 10 - "World State Entities"
Cohesion: 0.21
Nodes (20): Agent, BenchmarkMetrics, ClimateState, District, LawCompliance, BaseModel, WorldState contract — the schema between every backend system and the frontend., The complete world state — a pure projection of database state. (+12 more)

### Community 11 - "Iso.js Rendering Engine"
Cohesion: 0.16
Nodes (18): depth(), depthSort(), gridToScreen(), engine/iso.js Grid Math Module, screenToGrid(), tileAt(), diamond(), esc() (+10 more)

### Community 12 - "Point-in-Time Schema & Lookahead Test"
Cohesion: 0.14
Nodes (16): LazyFrame, OHLCVBar, PointInTimeFrame, DataFrame, datetime, Point-in-time OHLCV schema and the structurally-enforced accessor.  Every stored, One normalised bar. source/ingested_at/revision are storage     bookkeeping, not, Wraps OHLCV rows. `as_of(cutoff)` is the only read path feature     code gets: f (+8 more)

### Community 13 - "Frontend World View & API"
Cohesion: 0.17
Nodes (13): fetchBuildings(), fetchScoreboard(), fetchWorldState(), WorldView(), attachCamera(), CameraHandle, LabelCandidate, overlaps() (+5 more)

### Community 14 - "Building Sprites & Registry"
Cohesion: 0.18
Nodes (17): desaturate(), drawBuilding(), heightFor(), hexToNumber(), shade(), classifyFootprint(), ConstructionPhase, FootprintClass (+9 more)

### Community 15 - "Scoreboard & World API Routes"
Cohesion: 0.14
Nodes (16): FastAPI, get_scoreboard(), Any, Scoreboard API endpoint., The ultimate question: system vs buy-and-hold., _verdict_label(), get_world_state(), get_world_tick() (+8 more)

### Community 16 - "Frontend TypeScript Config"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 17 - "Frontend Isometric Projection & Monument"
Cohesion: 0.25
Nodes (12): depthOf(), gridToScreen(), Layer, ScreenPoint, screenToGrid(), createMonument(), heightForEquity(), MonumentHandle (+4 more)

### Community 18 - "App Entrypoint & Static Serving"
Cohesion: 0.20
Nodes (13): FileResponse, Start the background task that pushes world state deltas over websockets.      R, start_background_updater(), api_info(), api_root(), lifespan(), Any, FastAPI application entry point.  Serves the API and (optionally) the static Nex (+5 more)

### Community 19 - "Frontend Type Definitions"
Cohesion: 0.17
Nodes (12): BenchmarkMetrics, BuildProgress, Climate, District, LawCompliance, PopulationByStatus, Scoreboard, ScoreboardResponse (+4 more)

### Community 20 - "Buildings API & World Broadcast"
Cohesion: 0.26
Nodes (11): _building_payload(), get_building(), get_buildings(), Any, ConstructionPhase, Buildings API endpoint — construction manifest for the world view.  Construction, Get all buildings with their real construction status., Get details for a specific building. (+3 more)

### Community 21 - "Builder Agent Rendering"
Cohesion: 0.24
Nodes (8): ACTIVITIES, Activity, activityFor(), BuildersHandle, createBuilders(), drawBody(), hatColorFor(), ROLE_FAMILY

### Community 22 - "World Construction & Drilldown"
Cohesion: 0.18
Nodes (8): get_entity_drilldown(), Get detailed metrics behind any clickable object in the world view., get_building_info(), Any, Construction manifest — maps each building to its prompt, activation tables, and, get_benchmark_curve(), Any, The €1,000 buy-and-hold equity curve. Empty until Prompt 2 fills it.

### Community 23 - "Append-Only History Tests"
Cohesion: 0.18
Nodes (3): Law 6: history is append-only. UPDATE, DELETE and TRUNCATE on experiments, resul, The specific whole-corpus bypass: one statement, all three tables., test_truncate_all_history_tables_in_one_statement_raises()

### Community 24 - "Social Preview Card Content"
Cohesion: 0.22
Nodes (10): 20 Skills (Claim), Autotiling (Tag), Canvas2D (Tag), Depth Sort (Tag), Isometric Farm Scene Illustration, Isometric Game Skills (Repository), MIT License, Seamless Terrain (Tag) (+2 more)

### Community 25 - "Health Check API"
Cohesion: 0.31
Nodes (9): _building_summary(), _count_phases(), health_check(), Any, ConstructionPhase, Health check endpoints.  /health/ is the liveness probe and deliberately touches, Liveness probe — always returns 200., Readiness probe — returns real system status from the database. (+1 more)

### Community 26 - "Ground & Road Rendering"
Cohesion: 0.42
Nodes (8): computeRoadTiles(), drawGround(), drawRoadTile(), footprintOf(), isInsideAnyFootprint(), TERRAIN_VARIANTS, terrainHash(), hashString()

### Community 27 - "Sprite Color Palette"
Cohesion: 0.33
Nodes (6): PALETTE, PALETTE_ENTRIES, PaletteFamily, PaletteValue, snapToPalette(), toRgb()

### Community 28 - "Iso Engine Package Manifest"
Cohesion: 0.22
Nodes (8): description, license, name, private, scripts, test, type, version

### Community 29 - "Construction Phase Determination"
Cohesion: 0.31
Nodes (9): collect_row_counts(), _count_rows(), determine_phase(), get_construction_phases(), AsyncSession, ConstructionPhase, Map a structure id + observed row counts to its construction phase.      Public, Count rows in every table any building activates on. (+1 more)

### Community 30 - "Building Layout Tests"
Cohesion: 0.43
Nodes (6): _bounds(), _overlaps(), Validates the hand-authored city layout in prometheus/world/construction.py.  No, test_minimum_one_tile_gap_between_all_buildings(), test_monument_clear_radius_is_unoccupied(), test_no_two_buildings_overlap()

### Community 31 - "Terrain Tile Set Assets"
Cohesion: 0.53
Nodes (6): Dirt Tile, Grass Tile, Plowed Soil Tile, Sand Tile, Isometric Tile Set (Grass, Water, Dirt, Sand, Plowed Soil), Water Tile

### Community 32 - "AgentQuant & Temple Prompts"
Cohesion: 0.50
Nodes (5): Every component earns its place (A/B ablation), AgentQuant — LLM agent loses to static baseline (published evidence), PROMPT 6 — Ablation harness (Temple of Knowledge awakens), PROMPT 9 — LLM research layer (Scholars arrive, gated by ablation), Temple of Knowledge (meta-learning building)

### Community 33 - "World Enums"
Cohesion: 0.60
Nodes (5): Enum, AgentRole, ConstructionPhase, ScoreboardVerdict, str

### Community 35 - "Paper-Only Law & Qubx Eval"
Cohesion: 0.50
Nodes (4): Law 5: No real money, ever, from code, The Harbour (paper trading building), PROMPT 8 — Paper trading (Harbour launches), Qubx evaluation (github.com/xLydianSoftware/Qubx)

### Community 40 - "Sample Map Rendering Assets"
Cohesion: 0.67
Nodes (3): engine/iso.js, sample-map.json, Sample Map SVG

### Community 43 - "Depth-Sorting Diagram Panels"
Cohesion: 0.67
Nodes (3): CORRECT Panel: Sorted by row+col, objects.sort((a,b) => (a.row + a.col) - (b.row + b.col)) Code Snippet, WRONG Panel: Draw Order Ignoring Depth

### Community 44 - "Terrain Tiling Comparison"
Cohesion: 1.00
Nodes (3): Do Not Fit (Misaligned Tiles), Fit Perfectly (Seamless Tiles), Game Terrain Tile Comparison

## Ambiguous Edges - Review These
- `Repo layout (prometheus/ package diagram)` → `Flat layout vs. CLAUDE.md's nested prometheus/ layout — flagged uncertainty`  [AMBIGUOUS]
  docs/superpowers/plans/2026-09-04-repo-init-and-laws.md · relation: conceptually_related_to
- `PROMPT 2 — Point-in-time data layer (Library rises)` → `Point-in-Time Data Layer Implementation Plan`  [AMBIGUOUS]
  docs/superpowers/plans/2026-09-06-point-in-time-data-layer.md · relation: implements

## Knowledge Gaps
- **166 isolated node(s):** `metadata`, `WorldView`, `nextConfig`, `name`, `version` (+161 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **46 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Repo layout (prometheus/ package diagram)` and `Flat layout vs. CLAUDE.md's nested prometheus/ layout — flagged uncertainty`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `PROMPT 2 — Point-in-time data layer (Library rises)` and `Point-in-Time Data Layer Implementation Plan`?**
  _Edge tagged AMBIGUOUS (relation: implements) - confidence is low._
- **Why does `PolicyVersion` connect `Risk & Research Policy Config` to `Core DB Schema & Survivorship`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Why does `get_session_factory()` connect `Buildings API & World Broadcast` to `Data Ingestion & Versioning`, `Core DB Schema & Survivorship`, `Scoreboard & World API Routes`, `World Construction & Drilldown`, `Health Check API`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **Why does `run_quality_checks()` connect `Data Quality Checks` to `Data Ingestion & Versioning`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **What connects `Alembic runs synchronously (psycopg), even though the app runtime is async (asyn`, `metadata`, `WorldView` to the rest of the system?**
  _244 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Isometric Skills Repo Overview` be split into smaller, more focused modules?**
  _Cohesion score 0.1178743961352657 - nodes in this community are weakly interconnected._