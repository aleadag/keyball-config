# GitHub Pages URL discoverability

## Decision

Make the rendered keymaps easy to find from both the repository landing page
and its README:

- Set the GitHub repository description to `Back up and visualize Keyball Vial
  configurations with Nix and GitHub Pages.`
- Set the GitHub repository website to
  `https://aleadag.github.io/keyball-config/`.
- Add `[View the rendered keymaps](https://aleadag.github.io/keyball-config/)`
  immediately below the README title.

## Scope

This change only updates repository metadata and adds the single README link.
It does not add a badge, duplicate deployment instructions, change the Pages
workflow or generated site, or introduce redirects.

## Verification

- Confirm the README link is immediately below the title and targets the exact
  Pages URL.
- Read the GitHub repository metadata back and confirm the description and
  website match the values above.
- Confirm the Pages URL remains reachable.
- Review the final diff to ensure no generated files or unrelated content were
  changed.

## Rollback

Revert the README change and restore or clear the repository description and
website fields. The change exposes only an already-public static-site URL and
does not introduce credentials or private data.
