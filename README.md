# BreezeSkills

A collection of agent skills. Each skill lives under `skills/<name>/` and
follows the shared `SKILL.md` frontmatter convention (`name` +
`description`), so it is discoverable by Codex, Claude Code, Cursor, and
other agents that support agent skills.

## Skills

| Skill | Description |
|---|---|
| `mcpe-native-modding` | Develop native mods and hooks for MCPE (Minecraft: Pocket Edition) Android arm64 in C++ (default) or Rust, supporting two runtimes: preloader (BedrockTools methodology), BreezeAPI (Dobby + QuickJS), and Rust (mtbinloader2 patterns). |

## Layout

```
skills/<name>/
├── SKILL.md          # entry: architecture, API table, standard workflow
├── references/       # load-on-demand deep references
└── scripts/          # Python helper scripts
```

## Agent entry guides

- `AGENTS.md` — Codex convention.
- `CLAUDE.md` — Claude Code / other-agent convention (identical guidance).

Both point to the skill entry and list the file map.

## License

Apache License 2.0. See `LICENSE`. Individual skills may carry their own
`NOTICE` file for attribution.
