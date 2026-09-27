# Experiments

Experiment outputs live here. This directory is tracked only to hold this README (and `.gitkeep`); raw run artifacts under `cells/`, traces, logs and project build directories are ignored by `.gitignore`.

Run layout (see `docs/experiments.md`):

```
experiments/<run_id>/
  MANIFEST.json
  cells/<task>/<rep>/...
  SUMMARY.json
  REPORT.md
```

Raw per-call archives under `cells/` are on disk only;structured summaries (`SUMMARY.json`, `REPORT.md`, `MANIFEST.json`) may be committed for a frozen run.
