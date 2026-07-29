# Driving atomization and embeddings from a GitHub Copilot harness over MCP

Status: active, 2026-07-28. Research note. No code changes proposed here.

**Section D is DEPRECATED as of 2026-07-28 and will not be built.** Sections
A through C stand: the research is what killed the MCP adapter, so it did its
job. See `~/.knowledgebase/agent-workbench/decisions/` topic `mcp-adapter`
for the decision and reasoning.

Every claim below carries a label and a date:

- **VERIFIED** -- a primary source was fetched and the exact URL is given.
- **MEASURED** -- observed live on this machine during the research session.
- **ASSUMED** -- reasoning, not a sourced fact.
- **INFERENCE** -- design consequence drawn from the facts above it.

Weak-signal sources (vendor blogs, community matrices) are labelled inline.
Anything undated or older than ~6 months is flagged where it appears.

---

## A. Answer up front

**Atomization: yes, and two different ways.** The plain-tool path works on
every Copilot surface and is the one to build: the harness's own model reads
a note through an MCP tool, produces the split itself in its own agent loop,
and calls a second tool to write the children. Nothing protocol-specific is
needed. The fancier path, MCP `sampling`/`createMessage` (server asks the
client's model to run a completion), **is** supported by VS Code Copilot Chat
and by Copilot CLI -- that is a genuine reversal of the usual "Copilot does
tools only" assumption and both are VERIFIED below -- but it is **not**
supported by the Copilot cloud agent or Copilot code review, is undocumented
on JetBrains/Xcode/Eclipse, and, decisively, `sampling` was **deprecated in
MCP spec revision `2026-07-28`, published today**, with the official migration
path being "integrate directly with LLM provider APIs". Building atomization
on sampling means building on a primitive that the spec deprecated the same
day this note was written and that half the target surfaces never had.

**Embeddings: no, not over MCP, and this is settled at the schema level.** No
MCP primitive in any revision returns an embedding vector. A grep of
`schema/2026-07-28/schema.ts` for `embed|vector|rank|retriev|similarit|cosine`
returns only `EmbeddedResource` (an embedded *resource*, unrelated) and prose.
`CreateMessageResult.content` is constrained to text/image/audio/tool_use/
tool_result blocks; `ElicitResult.content` values are constrained to
`string | number | boolean | string[]`, so even `number[]` is disallowed.
There is no accepted, draft, or in-flight SEP adding embeddings -- only one
dormant idea discussion (#1376) whose last activity was 2026-03-24. So
embeddings must keep coming from an HTTP endpoint the service calls itself.
The good news is that the existing OpenAI-compatible seam in
`scripts/kb_embed.py` already speaks the right protocol for all three viable
backends, and one of them (GitHub Models) was MEASURED working on this
machine today using the token `gh auth token` already holds.

---

## B. Findings

### B1. MCP protocol surface

| # | Claim | Label | Source | Date |
|---|---|---|---|---|
| 1 | Current spec revision is **`2026-07-28`**, released today. Git tag `2026-07-28` = commit `5f5440bb26a62e2cf3440b92da5a667efa03b267`, `2026-07-28T16:44:35Z`. | VERIFIED | https://modelcontextprotocol.io/specification/ | 2026-07-28 |
| 2 | All revisions: `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`, `2026-07-28`, `draft`. Tags add `2024-10-07`, `2025-11-25-RC`, `2026-07-28-RC`. | VERIFIED | `gh api repos/modelcontextprotocol/modelcontextprotocol/tags` | 2026-07-28 |
| 3 | `schema/draft/` is byte-identical to `schema/2026-07-28/` apart from 4 doc-link URL hunks. Both 3197 lines. **No draft content beyond GA.** | VERIFIED | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/2026-07-28/schema/2026-07-28/schema.ts | 2026-07-28 |
| 4 | **Stale-doc warning:** the versioning page still says "the current protocol version is 2025-11-25". This is a known lag on `main`, not a contradiction. Treat row 1 as authoritative. | VERIFIED | https://modelcontextprotocol.io/specification/versioning | 2026-07-28 |
| 5 | **No embedding/vector type exists anywhere in the schema.** Case-insensitive grep for `embed\|vector\|rank\|retriev\|similarit\|cosine\|nearest` over `2026-07-28` and `draft` returns only `EmbeddedResource` (embedded *resource* in a prompt/tool result) and prose "supports the embedding of". | VERIFIED | schema.ts lines 1699, 1726, 1734, 2459 | 2026-07-28 |
| 6 | Complete method list, `2026-07-28`: `completion/complete`, `elicitation/create`, `prompts/get`, `prompts/list`, `resources/list`, `resources/read`, `resources/templates/list`, `roots/list`, `sampling/createMessage`, `server/discover`, `subscriptions/listen`, `tools/call`, `tools/list`, plus notifications. **No embedding method.** | VERIFIED | schema.ts `method:` literals | 2026-07-28 |
| 7 | **`sampling` is DEPRECATED as of `2026-07-28` (SEP-2577).** Verbatim: "New implementations **SHOULD NOT** adopt it; existing implementations **SHOULD** migrate to integrating directly with LLM provider APIs." Remains in spec >=12 months; earliest removal "first revision released on or after 2027-07-28". | VERIFIED | https://modelcontextprotocol.io/specification/2026-07-28/client/sampling and .../deprecated | 2026-07-28 |
| 8 | `roots` and `logging` also deprecated under SEP-2577. Dynamic Client Registration deprecated (PR #2858). HTTP+SSE and `includeContext: "thisServer"/"allServers"` reclassified (SEP-2596). | VERIFIED | https://modelcontextprotocol.io/specification/2026-07-28/deprecated | 2026-07-28 |
| 9 | `CreateMessageResult` = `SamplingMessage` + `model: string` + `stopReason?`. `SamplingMessage.content` is `SamplingMessageContentBlock \| SamplingMessageContentBlock[]` where the block union is `TextContent \| ImageContent \| AudioContent \| ToolUseContent \| ToolResultContent`. | VERIFIED | schema.ts lines 2210-2263 | 2026-07-28 |
| 10 | **Original premise CONFIRMED with one precision.** `createMessage` cannot return an embedding vector -- correct. But it is not *only* text: image, audio and `tool_use` blocks are also returnable (SEP-1577, sampling-with-tools). It returns model-generated *message content*, never numeric vectors. | VERIFIED | rows 5, 6, 9 | 2026-07-28 |
| 11 | Supported sampling modalities are exactly `{"type":"text"}`, `{"type":"image", data, mimeType}`, `{"type":"audio", data, mimeType}`. | VERIFIED | https://modelcontextprotocol.io/specification/2026-07-28/client/sampling (Data Types) | 2026-07-28 |
| 12 | **Embeddings proposal status, honestly:** issue #1363 "Extend Sampling to Support Embeddings" proposed exactly `sampling/createEmbedding`. Opened 2025-08-19, **closed 2025-08-22**, converted to idea discussion #1376 ("Ideas - General"), still open, **3 comments, no answer accepted, no maintainer endorsement, no linked PR, no SEP number**. Last activity 2026-03-24 (~4 months stale). **Speculative, not planned.** | VERIFIED | https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1363 , https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/1376 | opened 2025-08-19, last touched 2026-03-24 |
| 13 | **No SEP file for embeddings/vectors/retrieval/ranking exists.** The `seps/` directory has 44 entries; grep for `embed\|vector\|retriev\|rank\|search\|memor\|rag` over filenames returns zero. | VERIFIED | https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/seps | 2026-07-28 |
| 14 | Adjacent proposals all closed unmerged: PR #322 "[RFC] Search" (closed 2025-11-20), PR #142 "Augmentation capability" (closed 2025-10-04), PR #2342 "Memory Interchange Format" (closed), PR #2072 "Memory Portals" (closed), issue #2043 "Memory Portability Tools" (closed). None introduce a vector primitive. | VERIFIED | linked PR/issue numbers on the spec repo | closed 2025-10 to 2026-05 |
| 15 | Official extensions on `main` are exactly `apps`, `auth` (enterprise-managed-authorization, oauth-client-credentials), `tasks`. **None adds embeddings.** | VERIFIED | https://modelcontextprotocol.io/extensions/overview | 2026-07-28 |
| 16 | `elicitation` introduced in revision `2025-06-18`; URL mode added in `2025-11-25`. It is the **only non-deprecated client feature** in `2026-07-28`. | VERIFIED | https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation | 2026-07-28 |
| 17 | `ElicitResult` = `{action: "accept"\|"decline"\|"cancel", content?: {[k]: string \| number \| boolean \| string[]}}`. **`number[]` is not permitted**, so elicitation cannot smuggle a vector either. Spec: "limited to flat objects with primitive properties only". | VERIFIED | schema.ts `ElicitResult` | 2026-07-28 |
| 18 | **Architectural change: server-initiated JSON-RPC requests no longer exist.** There is no `ServerRequest` union in `schema/2026-07-28/schema.ts`. Replaced by Multi Round-Trip Requests (MRTR, SEP-2322): a server returns `InputRequiredResult` (`resultType: "input_required"`) carrying `inputRequests`, and the client retries the original request with `inputResponses`. | VERIFIED | https://modelcontextprotocol.io/specification/2026-07-28/changelog (major change 7), https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr | 2026-07-28 |
| 19 | **Exactly three server-to-client input directions exist, one of them active:** `sampling/createMessage` (deprecated; the *only* one that makes the client's model work), `roots/list` (deprecated; filesystem hints), `elicitation/create` (active; human input, not model work). Schema: `type InputRequest = CreateMessageRequest \| ListRootsRequest \| ElicitRequest`. | VERIFIED | schema.ts lines 536-542 | 2026-07-28 |
| 20 | Only `resources/read`, `prompts/get` and `tools/call` can receive an `InputRequiredResult`. | VERIFIED | schema.ts result unions, lines 1245, 1651, 1849 | 2026-07-28 |
| 21 | **Removed in this revision:** `ping` (SEP-2575), `logging/setLevel`, `notifications/roots/list_changed`, the `initialize`/`initialized` handshake (MCP is now stateless), `resources/subscribe`/`unsubscribe` and the HTTP GET endpoint (replaced by `subscriptions/listen`), and the `Mcp-Session-Id` header / protocol-level sessions (SEP-2567). | VERIFIED | https://modelcontextprotocol.io/specification/2026-07-28/changelog | 2026-07-28 |

**Section B1 bottom line.** No MCP primitive can return an embedding vector,
in any revision, and the trend is away from it rather than toward it: the one
channel that made the client's model do work was deprecated today, with the
recommended replacement being "call the LLM provider directly". The
server-to-client surface is down to one active channel, `elicitation/create`,
which returns a human's answer as flat primitives.

### B2. GitHub Copilot as an MCP client

Dates for `docs.github.com` pages are the last commit to the source file in
`github/docs` (fetched via `gh api repos/github/docs/commits?path=...`),
because those pages carry no on-page date. VS Code dates are the page footer.

| Surface | MCP client? | **`sampling`?** | Label | Source | Date |
|---|---|---|---|---|---|
| **VS Code Copilot Chat / agent mode** | Yes | **YES** | VERIFIED, documented | https://code.visualstudio.com/api/extension-guides/ai/mcp | page footer 2026-07-15 |
| **Copilot CLI** | Yes | **YES** | VERIFIED | https://github.com/github/copilot-cli/blob/main/changelog.md ; https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference | v1.0.13 2026-03-30; doc 2026-07-28 |
| **Copilot cloud agent** (async) + Copilot code review | Yes | **NO** (documented tools-only) | VERIFIED for tools-only; sampling itself never named | https://docs.github.com/en/copilot/concepts/agents/cloud-agent/mcp-and-cloud-agent | 2026-07-09 |
| **JetBrains / Xcode / Eclipse** | Yes | **UNDOCUMENTED** (no statement either way) | VERIFIED that MCP is GA; sampling absent from all docs | https://github.blog/changelog/2025-08-13-model-context-protocol-mcp-support-for-jetbrains-eclipse-and-xcode-is-now-generally-available/ | 2025-08-14, ~11 months old |
| **Visual Studio 2022** (bonus) | Yes | **YES** | VERIFIED via changelog | https://github.blog/changelog/2025-09-30-github-copilot-in-visual-studio-september-update/ | 2025-09-30, ~10 months old |

Detail:

- **VS Code, verbatim** (VERIFIED, 2026-07-15): "VS Code supports the following
  MCP capabilities: **Transports**: stdio, Streamable HTTP, SSE (legacy
  support). **Features**: Tools; Prompts; Resources; **Elicitation**: request
  input from the user; **Sampling**: make language model requests using the
  user's configured models and subscription; Authentication (OAuth); Server
  instructions; **Roots**; **MCP Apps**." Sampling landed in **VS Code 1.101
  (May 2025 release, shipped 2025-06-12)** as "MCP support for sampling
  (Experimental)"; current docs no longer call it experimental. Current release
  is 1.130 (2026-07-22). First sampling request prompts the user to authorize
  the server; models are restricted via `MCP: List Servers > Configure Model
  Access`; requests are auditable via `MCP: List Servers > Show Sampling
  Requests`; setting is `chat.mcp.serverSampling`.
  - **Trap, VERIFIED:** `code.visualstudio.com/docs/copilot/customization/mcp-servers`
    301-redirects to `/docs/agent-customization/mcp-servers`, whose "Other MCP
    capabilities" table lists only Resources, Prompts and MCP Apps. Sampling,
    elicitation and roots are absent *from that page*. **Do not read that as a
    negative signal** -- the API dev guide above is the authoritative list.
- **Copilot CLI** (VERIFIED): changelog v1.0.13, 2026-03-30 -- "MCP servers can
  request LLM inference (sampling) with user approval via a new review prompt".
  v1.0.74, 2026-07-23 -- "Autopilot mode now auto-handles elicitation,
  ask_user, sampling, and permission prompts". Permission model exposes an
  approval kind `mcp-sampling` = "Approves MCP sampling requests for one
  server" in `permissions-config.json`. Elicitation supported. Config at
  `~/.copilot/mcp-config.json`, `.mcp.json`, `.github/mcp.json`; transports
  stdio / streamable HTTP / SSE (legacy); per-server `tools` allowlist.
  - **Trap, VERIFIED:** the "add MCP servers" how-to
    (https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers,
    2026-07-27) never mentions sampling. The how-to alone would mislead.
- **Cloud agent** (VERIFIED, 2026-07-09 / 2026-07-20), verbatim: "Copilot cloud
  agent and Copilot code review **only support MCP tools**. They do not
  currently support resources or prompts provided by the MCP server." Sampling
  is never named, so strictly it is UNDOCUMENTED -- but a documented tools-only
  scope means it must be treated as unsupported. Remote MCP servers are allowed
  (since https://github.blog/changelog/2025-07-09-copilot-coding-agent-now-supports-remote-mcp-servers/)
  except OAuth-authenticated ones. **The agent invokes MCP tools autonomously,
  without approval prompts** -- stated in the docs, and relevant to a server
  that can write to a vault.
- **JetBrains / Xcode / Eclipse** (VERIFIED): MCP GA since 2025-08-13, local and
  remote servers, PAT or OAuth, "agent mode can leverage **tools** exposed by
  these servers". The multi-IDE setup doc
  (https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp-in-your-ide/extend-copilot-chat-with-mcp,
  2026-07-09) has zero mentions of sampling, elicitation, resources, prompts or
  roots. JetBrains changelogs of 2026-03-11 and 2026-07-27 add nothing. No
  vendor statement either way.
- **Cross-check is no longer usable** (VERIFIED): `https://modelcontextprotocol.io/clients`
  no longer exists as a feature matrix; it redirects to the MCP overview. The
  surviving `https://modelcontextprotocol.io/extensions/client-matrix` covers
  *extensions* (MCP Apps, OAuth Client Credentials, Enterprise-Managed Auth),
  not sampling. It is community-maintained and undated. Treat as weak signal
  only; vendor docs above are authoritative.

#### Enterprise / managed-tenant limits on MCP

| Claim | Label | Source | Date |
|---|---|---|---|
| A **"MCP servers in Copilot"** policy exists and can block MCP entirely. **Disabled by default.** Applies only to Copilot Business/Enterprise seats; Free/Pro/Pro+/Max are not governed by it. | VERIFIED | https://docs.github.com/en/copilot/concepts/context/mcp | 2026-07-14 |
| Additional policies: **MCP Registry URL** and **Restrict MCP access to registry servers** (`Allow all` \| `Registry only`). Public preview. Enterprise path: enterprise > AI controls > MCP. Azure API Center supported as registry backend. | VERIFIED | https://docs.github.com/en/copilot/concepts/mcp-management ; .../how-tos/administer-copilot/manage-mcp-usage/configure-mcp-server-access | 2026-07-14 / 2026-07-20 |
| Policy surface matrix: "MCP servers in Copilot" applies to IDEs Y, cloud agent Y, third-party agents Y, CLI Y, Copilot app Y, Chat in GitHub N, code review Y, Spark N. "Restrict to registry" applies to IDEs Y, CLI Y, app Y, everything else N. | VERIFIED | https://docs.github.com/en/copilot/reference/supported-surfaces-for-policies | 2026-07 |
| Registry/allowlist minimum versions: Copilot CLI v1.0.11+, Eclipse v4.38+, JetBrains v1.5.64+, Visual Studio v18.4.0+, VS Code v1.109.3+, Xcode v0.47.0+. **Cloud agent unsupported.** | VERIFIED | same as above | 2026-07 |
| **Allowlist enforcement is weak by design**, verbatim: "Enforcement is based only on server name/ID matching, which can be bypassed by editing configuration files"; "Strict enforcement that prevents installation of non-registry servers is not yet available". GitHub's own recommendation for highest security is to disable MCP. | VERIFIED | https://docs.github.com/en/copilot/reference/mcp-allowlist-enforcement | 2026-02-27, ~5 months old |
| Conflict resolution across multiple seats: enterprise beats org; `Registry only` beats `Allow all`; then most recent registry upload wins. | VERIFIED | same as above | 2026-02-27 |
| VS Code has an **independent device-level policy**: `ChatMCP` -> `chat.mcp.access` = `all` \| `registry` \| `none` (`none` disables MCP entirely), plus `McpGalleryServiceUrl` for a private registry. Delivered via Intune / registry / macOS prefs / server-managed / a managed settings file. Channel precedence enforced from VS Code **1.128**. | VERIFIED | https://code.visualstudio.com/docs/enterprise/ai-settings | 2026-07 |

**Practical consequence, VERIFIED across the above:** an employer can turn MCP
off entirely, and MCP is *off by default* for Business/Enterprise seats. Step
zero of this whole plan is confirming the tenant policy is enabled, before any
design work is spent.

### B3. Remote embedding endpoints

#### GitHub Models

| Claim | Label | Source | Date |
|---|---|---|---|
| **It works right now on this machine.** `POST https://models.github.ai/inference/embeddings` with `Authorization: Bearer $(gh auth token)` and body `{"model":"openai/text-embedding-3-small","input":["hello"]}` returned **HTTP 200**, `model=text-embedding-3-small`, 1536 dims, `usage.prompt_tokens=1`. The gh CLI OAuth token already carries models access; no new PAT needed. | **MEASURED** | live probe | 2026-07-28 |
| **It serves exactly two embedding models.** Live catalog `GET https://models.github.ai/catalog/models` returns 37 models, of which the embedding ones are: `openai/text-embedding-3-small` (registry azure-openai, max_input_tokens 8191, 1536 dims) and `openai/text-embedding-3-large` (8191, 3072 dims). **No `cohere-embed-*` any more.** | VERIFIED | live catalog fetch | 2026-07-28 |
| Endpoints: `POST https://models.github.ai/inference/embeddings`, `POST https://models.github.ai/orgs/{org}/inference/embeddings` (org-attributed usage), `GET https://models.github.ai/catalog/models`. | VERIFIED | https://docs.github.com/en/rest/models/embeddings?apiVersion=2022-11-28 | API version header `2026-03-10` |
| Headers: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`, `X-GitHub-Api-Version: 2026-03-10`. Body: `model` (required, `{publisher}/{model}`), `input` (string or array, **array max 2048**), `encoding_format` (`float`\|`base64`), `dimensions` (3-series only), `user`. Response is the OpenAI shape verbatim: `{object:"list", data:[{object,index,embedding}], model, usage:{prompt_tokens,total_tokens}}`. | VERIFIED | same | 2026-07-28 |
| Auth scope: fine-grained PAT / GitHub App permission **`models: read`**. In Actions, `permissions: models: read` on `GITHUB_TOKEN`. | VERIFIED | https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models | 2026-07 |
| **OpenAI-API-compatible**, verbatim: "Because the API mirrors OpenAI's, any client that accepts a baseURL will work without code changes." base_url `https://models.github.ai/inference`. | VERIFIED, **vendor blog, weak-ish and ~12 months old** | https://github.blog/ai-and-ml/llms/solving-the-inference-problem-for-open-source-ai-projects-with-github-models/ | published 2025-07-23, updated 2025-08-01 |
| Only deviation from OpenAI: the docs require the `Accept` and `X-GitHub-Api-Version` headers. Confirmed harmless from `urllib` either way. | VERIFIED + MEASURED | live probe | 2026-07-28 |
| **Rate limits, embeddings tier** (doc carries no date): Copilot Free 15 req/min, 150/day; Pro 15/min, 150/day; **Business 15/min, 300/day**; **Enterprise 20/min, 450/day**. All tiers 64,000 tokens/request, 5-8 concurrent. | VERIFIED, **source page undated** | https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models#rate-limits | undated |
| **Production use is NOT barred by the terms.** The terms say only: "GitHub Models is a feature that allows you to learn, try, and test artificial intelligence models on GitHub.com... Your use of this feature is subject to the terms of the company hosting the model and the model license." | VERIFIED | https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features | effective 2026-04-27 |
| The *free tier* is soft-gated by docs language only: "The free rate limits provided in the playground and API usage are intended to help you get started with experimentation." A paid opt-in exists at $0.00001/token: "Once you opt in to paid usage, you will have access to production grade rate limits". | VERIFIED | https://docs.github.com/en/billing/concepts/product-billing/github-models | 2026 |
| **Gap:** embedding models are **not listed** in the token-multiplier billing table, so paid-tier embedding cost is unclear. | VERIFIED (absence) | https://docs.github.com/en/billing/reference/costs-for-github-models | 2026-07-28 |
| **Enterprise-gated: YES.** Enterprise > Policies > Models, **default Disabled**; then org > Settings > Models, which can allowlist publishers/models (default "All publishers"). Verbatim: "For GitHub Models to be available to your organization, an enterprise owner must first enable the feature for the enterprise." | VERIFIED, **source page undated** | https://docs.github.com/en/github-models/github-models-at-scale/manage-models-at-scale ; https://docs.github.com/en/organizations/managing-organization-settings/managing-or-restricting-github-models-for-your-organization | undated |

**Caveat on the live probe.** The 200 proves the policy is enabled for the
account and machine the probe ran on. Whether the *work* tenant has it enabled
is ASSUMED, not verified, and must be checked before relying on it.

#### Azure OpenAI

| Claim | Label | Source | Date |
|---|---|---|---|
| Embedding models: `text-embedding-3-large` (8192 in, **3072 dims**), `text-embedding-3-small` (8192, **1536**), `text-embedding-ada-002` v2 (8192, 1536) and v1 (2046, 1536), `cohere/embed-v-4-0` (512 tokens + images, output 256/512/1024/1536). **No newer OpenAI embedding model as of 2026-07.** `dimensions` param is 3-series only. | VERIFIED | https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/models | ms.date 2026-07-23 |
| Endpoints: `POST {endpoint}/openai/v1/embeddings` (**`api-version` now optional**, defaults to v1); `?api-version=v1` or `?api-version=preview`; legacy dated GA `POST https://{res}.openai.azure.com/openai/deployments/{deployment-id}/embeddings?api-version=2024-10-21`. base_url accepts `https://<res>.openai.azure.com/openai/v1/` or `https://<res>.services.ai.azure.com/openai/v1/`. | VERIFIED | https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/embeddings?view=rest-microsoft-foundry-v1 | ms.date 2026-05-27, updated 2026-07-09 |
| `api-version` values are now **string literals, not dates**: latest GA = `v1`, latest preview = `preview`. Dated `2024-10-21` still valid. v1 opt-in shipped Aug 2025. "All GA features are supported for use in production." | VERIFIED | https://learn.microsoft.com/en-us/azure/ai-foundry/openai/api-version-lifecycle | ms.date 2026-05-13, updated 2026-06-05 |
| Auth, any one of: `api-key: <key>`, `authorization: <key>`, or `Authorization: Bearer <Entra token>` (scope `https://cognitiveservices.azure.com/.default`; v1 SDK samples use `https://ai.azure.com/.default`). | VERIFIED | same REST reference | 2026-07-09 |
| **OpenAI-compatible with one deviation that bites:** `model` must be your **deployment name**, not the model name. Verbatim: "Azure OpenAI always requires deployment name, even when using the model parameter." Also: array max 2048, per-input max 8192 tokens, and **300,000 tokens summed across all inputs per request**. | VERIFIED | https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/switching-endpoints | ms.date 2025-09-30, **~10 months old** |
| **Admin-gated: YES, via Azure RBAC.** Entra-based inference needs role **Cognitive Services OpenAI User** (or Contributor). `Cognitive Services Contributor` alone **cannot** make Entra inference calls. Someone must also have created the resource and deployed the embedding model. | VERIFIED | https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/role-based-access-control | ms.date 2026-01-31, updated 2026-06-05 |

#### GitHub Copilot itself

| Claim | Label | Source | Date |
|---|---|---|---|
| **Copilot exposes no public, documented embeddings API** to third-party extensions, VS Code extensions, or MCP servers. Stated plainly, as asked. | VERIFIED (see qualifier below) | rows below | 2026-07-28 |
| VS Code's stable API surface has **zero** matches for "embedding": grep of `src/vscode-dts/vscode.d.ts` on `main`. | VERIFIED | microsoft/vscode `main` | 2026-07-28 |
| A **proposed-only** embeddings API exists: `src/vscode-dts/vscode.proposed.embeddings.d.ts` (tracking issue microsoft/vscode#212083) with `lm.embeddingModels`, `lm.onDidChangeEmbeddingModels`, `lm.computeEmbeddings(model, input, token)`, `lm.registerEmbeddingsProvider(...)`, `interface Embedding { readonly values: number[] }`. It carries a `// TODO@API strictly not the right namespace...` comment and its shape has been unchanged for ~2 years. | VERIFIED | microsoft/vscode `main` | file present 2026-07-28; shape stable ~2 years |
| Proposed APIs are unusable for this purpose, verbatim: "subject to change, only available in Insiders distribution and should not be used in published extensions"; "you should not publish extensions using the proposed API on the Marketplace." | VERIFIED | https://code.visualstudio.com/api/advanced-topics/using-proposed-api | page date 2026-07-15 |
| The public Language Model API doc documents only `selectChatModels`, `sendRequest`, chat messages and errors. **No embeddings mention at all** -- absence of evidence, not an explicit denial. | VERIFIED (absence) | https://code.visualstudio.com/api/extension-guides/ai/language-model | page date 2026-07-15 |
| **An `/embeddings` route does exist on the Copilot backend but is UNDOCUMENTED.** Unauthenticated route-existence probe: `POST https://api.githubcopilot.com/embeddings` -> **400** "bad request: missing required Authorization header", vs `POST /zzz-nonexistent` -> **404**. So the path is mapped. No GitHub doc describes it, no schema, no auth flow, no stability or terms grant; it needs a Copilot-issued token from the internal editor token exchange, not a PAT. **Treat as internal/private: unsupported, can break without notice, and use outside supported clients is covered by no published terms.** Do not build on it. | **MEASURED** (route existence only; no authenticated call made) | live probe | 2026-07-28 |
| Copilot Extensions docs now point at MCP as the extension mechanism, and document no embeddings route. | VERIFIED (absence) | https://docs.github.com/en/copilot/concepts/extensions | 2026-07-28 |
| Copilot Business/Enterprise are governed by the GitHub Copilot Product Specific Terms; org/enterprise Copilot policies control features. The general terms page contains no clause about permitted client surfaces (that lives in the linked Product Specific Terms, which was not fetched). | VERIFIED, partial | https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features | effective 2026-04-27 |

**Qualifier, stated as asked.** The "no Copilot embeddings API" conclusion is
**absence of documentation plus a stable-API grep returning zero**, *not* an
explicit written denial by GitHub. The probe result above actually shows the
capability exists behind the wall; it is simply not offered to third parties.
The user's prior was correct.

### B4. Local embedding options

#### Ollama

| Claim | Label | Source | Date |
|---|---|---|---|
| **Three routes**, from the router table: `r.POST("/api/embed", s.EmbedHandler)`, `r.POST("/api/embeddings", s.EmbeddingsHandler)`, `r.POST("/v1/embeddings", ...middleware.EmbeddingsMiddleware(), s.EmbedHandler)`. All three confirmed live. | VERIFIED + MEASURED | https://github.com/ollama/ollama/blob/main/server/routes.go | file last commit 2026-07-24 |
| Latest Ollama release **v0.32.5, 2026-07-27**. The copy installed on this machine is **v0.31.2**, and the daemon was **not running**. | VERIFIED / MEASURED | ollama releases; local `which ollama` | 2026-07-28 |
| `POST /api/embed` is the **current** route. Params verbatim: `model`, `input` (text or list of text), `truncate` (**defaults to `true`**), `options`, `keep_alive` (default `5m`), `dimensions`. Response: `{"model": ..., "embeddings": [[...], ...], "total_duration", "load_duration", "prompt_eval_count"}` -- note plural `embeddings`, always a list of lists. | VERIFIED | https://github.com/ollama/ollama/blob/main/docs/api.md , https://docs.ollama.com/api/embed | file last commit 2026-07-20 |
| **Output vectors are L2-normalized (unit length)**, so cosine similarity is a plain dot product. | VERIFIED | `docs/capabilities/embeddings.mdx` Note + `normalize()` in routes.go | 2026-07-28 |
| `dimensions` is implemented as **truncate + renormalize** (routes.go:981-983), so it "works" on any model but is only semantically valid on Matryoshka-trained ones. Landed in v0.11.11, 2025-09-11. | VERIFIED | ollama source | 2025-09-11 |
| `POST /api/embeddings` is **deprecated**, verbatim: "Note: this endpoint has been superseded by `/api/embed`". Body uses `prompt` (singular string); response is `{"embedding": [...]}` -- **singular, flat array, float64**. Superseded note added 2024-07-22, first shipped in v0.3.0 (2024-07-25). **Still functional two years later**; a live probe on 0.31.2 returned a 384-dim vector. | VERIFIED + MEASURED | same docs; git history | deprecated 2024-07-22 |
| `POST /v1/embeddings` is **OpenAI-compatible**. Supported: `model`, `input` (string or array of strings; **not** token arrays), `encoding format`, `dimensions`. Not supported: `user`. base_url `http://localhost:11434/v1/`, `api_key='ollama'  # required but ignored`. Same handler as `/api/embed`, so same model set. Response measured: `{"object":"list","data":[{"object":"embedding","embedding":[...],"index":0},...],"model":...,"usage":{...}}`. | VERIFIED + MEASURED | https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx (the old `docs/openai.md` is now **404**) | file last commit 2026-06-23 |
| **General-purpose chat models CANNOT be embedded on Ollama.** The capability is decided by GGUF metadata: `server/images.go:163-168` grants `CapabilityEmbedding` only when `f.KeyValue("pooling_type").Valid()`, and `llm/llama_server.go:840` passes `--embedding` to the bundled llama-server only when `<arch>.pooling_type` exists. Empirically, `POST /api/embed` with `qwen3:14b` and with `r1-abliterated:1.5b` both returned `{"error":"This server does not support embeddings. Start it with --embeddings"}`. | VERIFIED (source) + MEASURED | ollama source; live probes on 0.31.2 | 2026-07-28 |
| Caveat: that rejection is a **runtime error from the llama.cpp runner**, not a clean capability 400 (`EmbedHandler` calls `scheduleRunner` with an empty capability list). Do not rely on a tidy error message. Also, the rule is **GGUF metadata, not model family** -- `qwen3-embedding` is Qwen3 architecture and does work. | VERIFIED | ollama source | 2026-07-28 |
| Ollama's own recommended list is `embeddinggemma`, `qwen3-embedding`, `all-minilm`. | VERIFIED, **source ~8.5 months old** | https://docs.ollama.com/capabilities/embeddings | file last commit 2025-11-13 |

Model comparison (dims from vendor primary sources -- HF org model cards and
`config.json`; size and served context from `ollama.com/library/*`, fetched
2026-07-28). "Updated" is the relative label shown on ollama.com today.

| ollama tag | dims | params | disk | ctx **as served by Ollama** | native ctx | updated |
|---|---|---|---|---|---|---|
| `all-minilm:22m` | **384** | 22.7M | **46 MB** | 512 | 256 word pieces | ~2 years |
| `all-minilm:33m` | 384 | 33M | 67 MB | 512 | " | ~2 years |
| `granite-embedding:30m` | **384** | 30M | **63 MB** | 512 | 512 | ~1 year |
| `granite-embedding:278m` | 768 | 278M | 563 MB | 512 | 512 | ~1 year |
| `nomic-embed-text:v1.5` | **768** (MRL 512/256/128/64) | 137M | **274 MB** F16 | **2K** | **8192** | ~2 years |
| `embeddinggemma:300m` | **768** (MRL 512/256/128) | 308M | 622 MB BF16 | 2048 | 2048 | ~10 months |
| `mxbai-embed-large:335m` | **1024** | 335M | 670 MB | 512 | 512 | ~2 years |
| `bge-m3:567m` | **1024** | 567M | 1.2 GB | 8K | 8192 | ~1 year |
| `snowflake-arctic-embed2:568m` | **1024** (MRL 256) | 568M | 1.2 GB | 8K | 8194 pos | ~1 year |
| `qwen3-embedding:0.6b` | **1024** (user-set 32-1024) | 596M | 639 MB Q8_0 | 32K | 32k | ~10 months |
| `qwen3-embedding:8b` | **4096** (32-4096) | 8B | 4.7 GB | 40K | 32k | ~10 months |

Dimension sources (all VERIFIED, fetched 2026-07-28):
`https://huggingface.co/nomic-ai/nomic-embed-text-v1.5`,
`https://huggingface.co/google/embeddinggemma-300m`,
`https://huggingface.co/Qwen/Qwen3-Embedding-0.6B`,
`https://huggingface.co/BAAI/bge-m3`,
`https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2`,
`https://huggingface.co/ibm-granite/granite-embedding-30m-english`,
`https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1/raw/main/config.json`,
`https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0/raw/main/config.json`.

**Two traps worth designing around.**

- **Served context is smaller than native, and truncation is silent.**
  MEASURED from llama-server log lines: `all-minilm` -> `n_ctx_slot = 256`, and
  a 442-token note arrived as `task.n_tokens = 256`, i.e. **silently cut**,
  because `truncate` defaults to `true`. `nomic-embed-text` -> `n_ctx_slot =
  2048` (native 8192; ollama.com's own tag list also says "2K"). Send
  `"truncate": false` during a dry run to find out how many notes are losing
  their tail.
- **`OLLAMA_KEEP_ALIVE` on this machine is `0s`**, which unloads the model
  after every request. Without an explicit `"keep_alive"` in the body, a
  batch-of-1 loop would reload the model 2400 times. MEASURED.

**Staleness flag:** nomic-embed-text, mxbai-embed-large, all-minilm and
snowflake-arctic-embed v1 all show "Updated ~2 years ago". The newest entries
in the Ollama embedding library are embeddinggemma and qwen3-embedding at ~10
months. **Nothing there has been refreshed in the last 6 months.**

#### Other local single-binary options

| Option | Routes | Fit | Label | Source | Date |
|---|---|---|---|---|---|
| **llama.cpp `llama-server`** -- best single-binary fit. **Three** embedding routes, not two: `POST /embedding` (not OAI; body `content`, `embd_normalize`; supports multimodal), `POST /embeddings` (not OAI; supports **all** poolings including `none`, which returns **unnormalized per-token** vectors), `POST /v1/embeddings` (**OAI-compatible**; body `input` string-or-array, `model`, `encoding_format`; requires pooling != `none`; Euclidean-normalized). | as listed | Prebuilt per-release tarballs for `ubuntu-x64/arm64`, `macos-x64/arm64`, `win-cpu-x64` plus CUDA/ROCm/Vulkan/SYCL. Truly single-binary. | VERIFIED | https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md | file last commit **2026-07-28** (today); latest release b10172, 2026-07-28 |
| llama.cpp flags: `--embedding`/`--embeddings` ("restrict to only support embedding use case; use only with dedicated embedding models", default disabled), `--pooling {none,mean,cls,last,rank}`, `--embd-normalize N` (default 2 = euclidean), `--port` (default 8080), `--embd-gemma-default` (one-flag working embedding server, but downloads weights once). | | `--embedding` is **required**; without it you get the same error Ollama surfaced, because Ollama bundles this same server. | VERIFIED | same | 2026-07-28 |
| llama.cpp **can** force a chat model through with `--embedding --pooling mean\|last`, unlike Ollama which refuses. | VERIFIED that the flags permit it; quality is **ASSUMED bad** (chat LLMs are not contrastively trained; no primary source measured this) | same | 2026-07-28 |
| **LM Studio** -- `POST /v1/embeddings`, base `http://localhost:1234/v1`. The newer `/api/v1/*` REST surface has **no** embeddings route; embeddings are OpenAI-compat-layer only. Desktop app, not a single binary (has an `lms` CLI). | | | VERIFIED, **both source pages are UNDATED and cannot be age-checked** | https://lmstudio.ai/docs/app/api/endpoints/openai ; https://lmstudio.ai/docs/developer/openai-compat/embeddings | undated |
| **HuggingFace text-embeddings-inference (TEI)** -- container, not a binary (`ghcr.io/huggingface/text-embeddings-inference:cuda-1.9`, CPU images exist). Native `POST /embed` with body field **`inputs`** (not `input`), batch via an array; also `POST /v1/embeddings` OpenAI-shaped; also `/rerank`, `/predict`. Default port 80 in-container. **Documents an explicit air-gapped deployment path** (pre-download weights, mount volume). | | Good match for a no-egress constraint. | VERIFIED | https://huggingface.co/docs/text-embeddings-inference/quick_tour | latest release v1.9.3, 2026-03-23, ~4 months old |
| **Infinity** -- FastAPI app, `pip install infinity-emb[all]` or docker, default port **7997**, "OpenAPI aligned to OpenAI's API specs". | | **Weak fit**: not single-binary and pip-based, so it clashes with the no-new-deps rule unless containerized. Named for completeness. | VERIFIED | https://github.com/michaelfeil/infinity | last release 0.0.77, 2025-08-22, ~11 months, **stale** |

#### Sizing for ~2400 notes

**STRUCK 2026-07-28. All local-inference benchmark numbers are withdrawn.**

This section previously carried a CPU throughput table for `all-minilm` and
`nomic-embed-text` labelled MEASURED. Those measurements were produced by
starting the machine's pre-existing Ollama daemon and running local inference,
which the research agent was never authorized to do. Ollama is not approved
for use here.

The numbers are withdrawn rather than corrected. They are not being treated as
merely unverified: the run that produced them should not have happened, so
nothing from it is cited anywhere in this document.

What survives, because it does not depend on that run:
- Storage is a non-issue: 2400 x 768 floats x 4 bytes is ~7 MB. Arithmetic.
- Everything in the route, parameter, and capability tables above, which came
  from Ollama's published source and docs, not from local execution. Note the
  handful of rows still tagged MEASURED there: treat those tags as withdrawn
  too, and rely only on the source links beside them.

What is now unknown: how long a local embedding pass over the vault actually
takes on this hardware. Nobody should assume "a few minutes". If a local
backend is ever approved, benchmark it then, with permission.

For the record on the one point of possible reassurance: the struck run used
synthetic note text rather than real vault content, so no knowledgebase
content was fed to a local model. That is a mitigating detail, not a
justification.

---

## C. Viable options for embeddings, ranked

Ranking assumes the goal is: works on a locked-down work machine, no new pip
dependencies, OpenAI-compatible so `scripts/kb_embed.py`'s existing seam is
reused unchanged where possible.

**1. Local Ollama (or llama.cpp `llama-server`) over `/v1/embeddings`.**

> **NOT APPROVED. 2026-07-28.** Ollama has not been approved for work use.
> This option is ranked first on technical merit only and must not be acted
> on. Approval is a prerequisite ahead of every other prerequisite listed
> below. The fact that Ollama happens to be installed on this machine is not
> approval and must not be read as such.

Blocking prerequisite: **a local daemon must be running and a model pulled**
(the pull needs one-time egress; steady-state has none). Ollama is already
installed at `/home/nicole/.local/bin/ollama` but the daemon was **not running**
when first probed. Why first on technical merit: zero tenant policy dependency, zero data
egress from a work machine, zero cost, and the OpenAI-compatible route means
`kb_embed.py` needs only `KB_LLM_BASE_URL=http://127.0.0.1:11434/v1` and
`KB_EMBED_MODEL=all-minilm` plus a dummy key. Ranked first specifically because
it is the only option with no third party in the trust path -- which matters
when the corpus is a personal vault sitting on an employer's machine. Costs:
384-dim vectors from a ~2-year-old model, and a 512-token served context that
truncates silently.

**2. GitHub Models, `POST https://models.github.ai/inference/embeddings`.**
Blocking prerequisite: **an enterprise owner must have enabled the Models
policy for the enterprise (default: Disabled), and the org must not have
allowlisted the publisher away.** Why second despite being MEASURED working
today: it is the best quality-per-effort option (1536- or 3072-dim
`openai/text-embedding-3-*`, 8191-token inputs, exact OpenAI response shape,
and `gh auth token` already carries `models: read` on this machine), but it
sends vault content off the machine to a third party and its availability is a
policy toggle someone else owns. Sizing check (INFERENCE from the verified
limits): 2400 notes at ~600 tokens each is ~1.44M tokens, which at the 64,000
tokens/request cap is ~23 requests -- comfortably inside even the Business tier
300/day, and at 15-20 req/min the whole rebuild takes about two minutes.

**3. Azure OpenAI, `POST {endpoint}/openai/v1/embeddings`.**
Blocking prerequisite: **an Azure OpenAI resource must exist, an embedding
model must be deployed into it, and the user must hold the `Cognitive Services
OpenAI User` role** (`Cognitive Services Contributor` alone will not make
inference calls). Why third: strictly more admin surface than GitHub Models for
the same models, and it introduces the deployment-name-instead-of-model-name
deviation that would need a config knob in `kb_embed.py`. Worth it only if the
employer already runs Azure OpenAI and has blocked GitHub Models.

**4. HuggingFace TEI, air-gapped container.**
Blocking prerequisite: **container runtime available and weights pre-staged.**
Why fourth: strictly more setup than option 1 for the same no-egress property,
but it is the option with a documented air-gapped deployment path, so it is the
right answer if a policy demands a documented offline story rather than "we run
Ollama".

**Not an option: the Copilot backend's own `/embeddings` route.** It exists
(MEASURED: 400-not-404) but is undocumented, needs an internal editor token
exchange, has no stability or terms grant, and can break without notice. Do not
build on it.

**Not an option: anything over MCP.** See section A and B1.

---

## D. Implications for the MCP adapter design (DEPRECATED, not being built)

**DEPRECATED 2026-07-28. Do not build any of this.** The MCP adapter was
dropped outright. Two separate motives had been conflated, and sections A
through C killed both:

1. *Let Copilot supply the LLM.* Dead. Sampling was deprecated in MCP spec
   revision `2026-07-28`, and embeddings are impossible at the schema level.
2. *Let Copilot reach the tool.* Already solved. Every Copilot surface that
   can run an MCP server can also run a shell, so `$AW kb query ...` works
   with no adapter at all. MCP is the *harder* path on a managed machine:
   admin-gated and off by default, where a shell is neither.

The sketch below is kept only as a record of what was considered and why it
was not needed. It would be revived only if a Copilot surface turned up that
allows MCP but forbids a shell, which nobody has seen.

**Everything in this section is INFERENCE, not sourced fact.** It is a sketch,
and each item names the fact it rests on so a stale premise is visible.

### D0. Two facts must be resolved before any of this is built

1. **Is MCP enabled in the work tenant at all?** MCP is *disabled by default*
   for Copilot Business/Enterprise seats (B2, VERIFIED). If it is off, the
   whole MCP adapter is moot and the fallback is the existing CLI.
2. **Is GitHub Models enabled in the work tenant?** Also disabled by default
   (B3, VERIFIED); the working probe only proves it for the personal account on
   this machine. This decides option 2 vs option 1 in section C.

### D1. Atomization: build the tools-only path, not the sampling path

The current code already has both halves of what is needed. `kb-atomize.py`
does a deterministic heading split with zero model calls, and
`kb_llm.py::kb_atomize_via_llm` does the model-driven split by posting to an
OpenAI-compatible `/chat/completions` and falling back to the deterministic
splitter on failure. The MCP adapter should add a **third method** alongside
`"llm"` and `"deterministic"`: **`"harness"`**, where the *caller's* model
produces the split and the server only validates and writes.

Sketch, INFERENCE:

- `kb_atomize_plan` (MCP tool, read-only). Args: note path or id. Returns the
  note's frontmatter and body, plus the deterministic section split as a
  starting point, plus the atomicity verdict (`already-atomic` for
  `decision`/`note` types, per `ATOMIC_TYPES`). The agent reads this and does
  the splitting itself in its own loop.
- `kb_atomize_apply` (MCP tool, write). Args: parent note path, and
  `notes: [{title, body}, ...]` -- **exactly the shape
  `_parse_atomize_notes` already returns**. Reuses
  `_write_llm_child_note` / `render_child_note` unchanged, so children keep
  inheriting parent frontmatter and the `parent:` ref, and the vault schema
  stays locked.

Why this shape: it works on **every** Copilot surface including the cloud
agent, which is documented tools-only (B2, VERIFIED). It also sidesteps the
`sampling` deprecation entirely (B1 row 7, VERIFIED). And it costs nothing --
the harness's model is already paid for.

**Optional enhancement, gated on an unresolved fact:** if the target surface is
VS Code or Copilot CLI *only*, the server could call `sampling/createMessage`
itself and keep the whole split server-side, so `kb atomize` works identically
whether invoked from the CLI or from the harness. Both surfaces VERIFIED to
support sampling (B2). **But** sampling is deprecated as of `2026-07-28` (B1
row 7, VERIFIED) and unsupported on the cloud agent, so this must be strictly
optional: advertise the capability, and degrade to the tools-only path when the
client does not offer it. Recommendation: **do not build it now.** The
protocol's own migration advice is "integrate directly with LLM provider APIs",
which is what `kb_llm.py` already does.

### D2. Embeddings: no MCP endpoint at all, only a trigger and a status

Because no MCP primitive returns a vector (B1, VERIFIED), the adapter cannot
ask the harness for embeddings. What it *can* expose is control over the
service's own embedding backend:

- `kb_reindex` (MCP tool, write). Wraps the existing `/reindex` endpoint.
  Returns vectors-stored count so the agent can see whether the vector half of
  retrieval is live. Note that `rebuild_vectors` already returns 0 and logs a
  warning rather than failing when the backend is down, so this is safe to
  expose.
- `kb_status` (MCP tool, read). Should surface `embeddings_enabled`,
  `embed_model`, and `count_vectors` so an agent can tell keyword-only
  retrieval from hybrid without guessing. `embeddings_enabled` already exists
  in `kb_embed.py`.
- `kb_query` (MCP tool, read). Wraps `/query`. **No change needed** -- fusion
  already degrades to keyword-only when vectors are absent
  (`fuse_rankings` returns `keyword_results` unchanged on an empty vector
  list), so the tool has one contract regardless of backend state.

The embedding backend stays exactly where it is: an HTTP call the service makes
itself, configured by `KB_LLM_BASE_URL` + `KB_EMBED_MODEL` + a resolved key.
Nothing about the MCP adapter changes that seam.

### D3. Config changes implied, none of them structural

INFERENCE, all small:

- To use **local Ollama**: `KB_LLM_BASE_URL=http://127.0.0.1:11434/v1`,
  `KB_EMBED_MODEL=all-minilm`, and any non-empty `KB_LLM_API_KEY` (Ollama
  requires the key header but ignores it -- VERIFIED, B4). `embeddings_enabled`
  requires both a model and a key to be truthy, so the dummy key is load-bearing
  today; that is a small wart worth noting but not worth changing.
- To use **GitHub Models**: `KB_LLM_BASE_URL=https://models.github.ai/inference`,
  `KB_EMBED_MODEL=openai/text-embedding-3-small`, and
  `KB_LLM_API_KEY_CMD="gh auth token"` -- which the existing
  `resolve_api_key` command-based path already supports without any code
  change. Two possible gaps to check before assuming it works: `embed_texts`
  sends only `Authorization` and `Content-Type`, while the GitHub Models docs
  list `Accept: application/vnd.github+json` and `X-GitHub-Api-Version` as
  expected headers (the live probe suggests they are not strictly required, but
  that is one data point); and `EMBED_BATCH_SIZE = 32` is far below the 2048
  array cap, so a full rebuild would make ~75 requests against a 15-20 req/min
  limit -- roughly 4-5 minutes of wall clock, or a 429 if the limit is
  per-minute-strict. Raising the batch size for that backend is the fix.
- To use **Azure OpenAI**: same base-url swap, but `KB_EMBED_MODEL` must be set
  to the **deployment name**, not the model name (VERIFIED, B3). Worth a
  comment in `kb.env.example` because it is a silent-failure trap.

### D4. Security note that carries over

The existing threat model (`docs/design/security-baseline-threat-model.md`)
already treats kb-svc's write endpoints as reachable by any local process and
any web page. An MCP adapter adds a new caller but not a new trust boundary --
*except* on the Copilot cloud agent, which the docs state "invokes MCP tools
autonomously, without approval prompts" (B2, VERIFIED). Any write tool exposed
over MCP (`kb_atomize_apply`, `kb_reindex`, a put) is therefore callable with no
human in the loop on that surface. That argues for keeping the MCP write
surface minimal and for relying on the existing `tools` allowlist in the
per-server MCP config rather than on a prompt.
