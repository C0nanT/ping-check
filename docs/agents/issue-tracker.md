# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/SPEC.md`
- Implementation tickets are `.scratch/<feature-slug>/tickets/<NN>-<slug>.md`, numbered from `01`
- Ticket state is recorded as a free-form `Status:` line near the top of each ticket file (no triage label vocabulary configured)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.
