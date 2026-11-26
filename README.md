# nlp-lab2-2-wow-text-adventure
# Azeroth Party Quest (Text-Based WoW Adventure)

A text-based *World of Warcraft* adventure game built for NLP Lab 2.2. Players create a character, complete starting-zone quests to level up and unlock skills, assemble a balanced 5-player party (1 Tank, 1 Healer, 3 DPS) with AI teammates, clear a three-stage dungeon, and receive an entertaining post-run review.

## Key Features

- **Character Creation & Starting Quests**: Choose a race and class, take on starting-zone quests, gain experience, level up, and unlock class skills.
- **5-Player Role-Balanced Party**: Choose your own role (`tank`, `healer`, or `dps`) and recruit AI companions while inspecting each candidate's name, race, class, role, and level to form a 1-Tank, 1-Healer, 3-DPS group.
- **Three-Stage Dungeon Run**: Progress through mob encounters, an elite guardian, and a final boss with dynamic tactical adaptation.
- **Multi-LLM Architecture & Output Digestion**: Uses distinct LLM calls for story narration/revision, outcome judgment, combat/memory summarization, boss adaptation, and post-run review, feeding prior LLM summaries and state logs back into subsequent turns.
- **Enjoyable Post-Run Review**: Generates a fun, fact-checked run review summarizing key moments, party highlights, and battle takeaways alongside saved game states.

## Project Structure

```text
.
├── wow_game.py                 # Main game loop, state management, and LLM pipelines
├── wow_config.json             # Model and directory configuration
├── requirements.txt            # Python dependencies
├── corpora/
│   └── wow/
│       ├── races_classes.json  # Races, classes, roles, stats, and unlockable skills
│       ├── starting_zones.json # Starting zones and starter quests
│       ├── teammates.json      # AI companion candidate pool
│       └── dungeon.json        # Three-stage dungeon encounters and boss mechanics
└── wow_output/
    ├── state/
    │   └── save_1.json         # Saved / final game state
    └── summary_1.txt           # Post-run review output
