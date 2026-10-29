# Working on simulated-market

Read README.md first. This guide describes the repository source, not an authorization to deploy or publish.

## Code map

- `docs/`: design, evidence or setup notes.
- `schema/`: source for this component.
- `tests/`: automated checks.
- `web/`: source for this component.
- `workspace/`: workspace source and recorded material.

## Safe first review

Start with `git status --short` and `git diff --check`. These inspect the working tree without starting the product. Follow the repository-specific setup and verification instructions in README.md; inspect the command and required environment before execution. A declared command is not proof that it ran.

## Evidence and data boundaries

Keep sample, recorded and live results distinct. Preserve sources and denominators for measured claims. Do not invent users, outcomes, screenshots or test results. Keep credentials, personal records and private prompts out of commits, logs and screenshots. Use only material already approved for this public repository. Provider requests may send data and consume quota. Review their recipient and scope first.

## Shipping

Use an isolated branch or worktree and preserve unrelated work. For documentation changes, check referenced files, setup commands and rendered images. Run relevant checks for code changes and report what was actually exercised. Opening a pull request does not authorize merging, deployment, posting or a submission.
