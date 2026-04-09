# yao-cli-tools

A growing collection of small CLI tools by Yao.

## Scope

This repository is intended for:

- focused command-line utilities
- reusable scripts that can later become standalone packages
- small experiments that are useful enough to keep and share

## Layout

- `tools/`: individual tools or small packages
- `tools/tokkit`: local-first usage ledger for AI coding tools

## Current tools

- [`tools/tokkit`](tools/tokkit/README.md): track tokens, cost, models, terminals, and clients across local AI coding workflows

## Publishing Rules

- each tool should have its own README
- each tool should document install and usage steps
- keep dependencies narrow and explicit
- prefer shipping tools that solve one clear problem well

## License

MIT
