# English documentation images

Prepared on 2026-10-24. Chinese assets are unchanged. The root README defaults to English; Russian and Korean README editions reuse these English assets. The Chinese edition retains its original Chinese images.

## Assets

| File | Use | Provenance |
| --- | --- | --- |
| [aimanager-hero.png](aimanager-hero.png) | README hero: **Get more value from your AI** | AI-generated English localization of the existing brand illustration; 1672 × 941 |
| [chatgpt-labcontext-demo-translated.png](chatgpt-labcontext-demo-translated.png) | ChatGPT accessing project context through LabContext | English translation/reconstruction of the existing Chinese conversation image, visibly labeled as translated; **not a new live execution screenshot**; 1805 × 871 |
| [aimanager-collaboration-demo.png](aimanager-collaboration-demo.png) | Six-step CLI/API collaboration example | Server-supplied English localization of the original output montage, preserving layout, code, and highlights; not a separate rerun; original 3360 × 3814 PNG |
| [aimanager-accounts.jpg](aimanager-accounts.jpg) | Accounts and official quotas | English product UI with synthetic demonstration data |
| [aimanager-connections.jpg](aimanager-connections.jpg) | Claude account connection and default selection | English product UI with synthetic demonstration data |
| [aimanager-analytics.jpg](aimanager-analytics.jpg) | Per-platform usage overview | English product UI with synthetic demonstration data |
| [aimanager-usage-trend.jpg](aimanager-usage-trend.jpg) | Supplemental token breakdown view | English product UI with synthetic demonstration data; viewport excerpt |
| [aimanager-workspaces.jpg](aimanager-workspaces.jpg) | Direct-path access and connection checks | English product UI with synthetic demonstration data |
| [aimanager-workspace-details.jpg](aimanager-workspace-details.jpg) | Supplemental registered-project card | English product UI with synthetic demonstration data; viewport excerpt |

## Capture notes

- UI images are browser captures, not generated UI mockups. The app's built-in language selector was set to English.
- The deployed Web UI was served through an isolated loopback documentation fixture. API responses used `apps/tests/workspace-console.spec.ts` demonstration fixtures, with their display labels translated. No live account API responses were used in the published images.
- Names, paths, balances, quotas, health states, and usage figures are examples, not production measurements. A healthy local connection is not proof of successful ChatGPT connector registration.
- Captures are 1424 × 717 JPEG viewport excerpts. The rightmost browser-extension controls were excluded from the frame. The images were not enlarged or converted to PNG to imply additional detail.
- The two PNG illustrations use the built-in image-generation tool. Exact prompts are saved in the adjacent `.prompt.txt` files. Original generated resolution is retained.
- The collaboration PNG was copied from the user-supplied server deliverable without resizing or recompression. It is separate from the two image-generation outputs.
- The production interface language was restored to Chinese. No production code, accounts, credentials, or runtime settings were changed for the demo data.

## Root README Markdown snippets

These paths assume the English Markdown file is in the repository root. Keep the provenance captions when publishing. For future non-Chinese README translations, reuse this directory instead of duplicating images or embedding Chinese screenshots.

```markdown
![AImanager — Get more value from your AI](docs/assets/en/aimanager-hero.png)

![ChatGPT uses LabContext to inspect project evidence — translated conversation excerpt](docs/assets/en/chatgpt-labcontext-demo-translated.png)
*English translation of an original Chinese conversation; not a new execution screenshot.*

![Six-step CLI and API collaboration](docs/assets/en/aimanager-collaboration-demo.png)
*English-localized output excerpts from the recorded example; not a separate rerun.*

![AImanager workspaces and direct-path access](docs/assets/en/aimanager-workspaces.jpg)

![AImanager accounts and quotas](docs/assets/en/aimanager-accounts.jpg)

![AImanager Claude Code connection management](docs/assets/en/aimanager-connections.jpg)

![AImanager per-platform usage analytics](docs/assets/en/aimanager-analytics.jpg)

*Product screenshots use demonstration data. Platform quotas and usage sources remain separate.*
```

Recommended order: hero → ChatGPT project-context example → server-supplied collaboration example → account/connection/usage screenshots. Use the supplemental screenshots only where a detailed section benefits from them.
