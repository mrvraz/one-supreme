# Hiveshire Blueprint: every check and its key

Generated from `page.html`. A key is the document id in the board's `checks` collection.
Tags: MUST (before launch), sec (safety feature), data, access, leak. Hiveshire's own checks live in `custom` (key `c-<id>`).

## 01 Idea & validation

Prove the problem is real before writing code, and spot early which data the idea will need.

### Define the problem

- `01-write-a-one-line-problem-statement` Write a one-line problem statement: Who has the problem, how often it hurts, and what they do about it today.
- `01-list-your-users-and-roles` List your users and roles: Customer, admin, staff, partner. Every role becomes an access rule later. [access]
- `01-sketch-the-core-user-journey` Sketch the core user journey: Map the 3–5 screens that deliver the main value. Ignore everything else for now.
- `01-name-the-moment-of-value` Name the moment of value: The point where a user first gets what they came for. Design everything to reach it fast.

### Validate demand

- `01-talk-to-10-potential-users` Talk to 10+ potential users: Ask about what they did last time, not whether they'd like your idea.
- `01-check-the-market` Check the market: Search trends, competitor reviews and communities show whether people pay to solve this.
- `01-run-a-smoke-test` Run a smoke test: A landing page with a waitlist measures real intent cheaply. [data]
- `01-fill-in-a-lean-canvas` Fill in a Lean Canvas: One page: problem, customers, value, channels, costs and revenue.

### Spot the risk early

- `01-list-the-data-the-idea-needs` List the data the idea needs: Write down every piece of personal data the app would collect or touch. [MUST data]
- `01-check-for-regulated-territory` Check for regulated territory: Payments, health, finance, children or EU users each bring their own rules. [data]
- `01-decide-what-you-will-not-collect` Decide what you will not collect: Data you never store can't leak. Cut every field that isn't essential. [data leak]
- `01-write-your-trust-promise` Write your trust promise: One sentence users can rely on, e.g. “We never sell or share your data.” [data]

### Scope the first version

- `01-choose-web-mobile-or-both` Choose web, mobile or both: A responsive web app is usually the fastest and cheapest first release.
- `01-cut-to-one-core-workflow` Cut to one core workflow: Ship the smallest thing that delivers the moment of value.
- `01-set-success-metrics` Set success metrics: Two or three numbers that prove it works, such as weekly active users or retention.
- `01-budget-for-security-not-just-build` Budget for security, not just build: Include hosting, tools, legal review and an external security test. [sec]

## 02 Plan & threat model

Turn the idea into requirements and decide up front what you're protecting, and from whom.

### Requirements

- `02-write-user-stories-with-abuse-cases` Write user stories with abuse cases: Next to each “As a user I can…”, add “As an attacker I try to…”. [sec]
- `02-pick-a-security-baseline` Pick a security baseline: OWASP ASVS Level 1 at minimum; Level 2 for any app holding personal data. [MUST sec]
- `02-set-uptime-and-recovery-targets` Set uptime and recovery targets: How long can you be down (RTO)? How much data can you lose (RPO)? [data]
- `02-plan-accessibility-from-day-one` Plan accessibility from day one: WCAG 2.2 AA is the common bar and a legal duty in many markets.

### Threat model

- `02-draw-a-data-flow-diagram` Draw a data-flow diagram: Boxes for users, app, database and vendors; arrows for data; dashed lines for trust boundaries. [sec data]
- `02-ask-the-four-questions` Ask the four questions: What are we building? What can go wrong? What will we do about it? Did we do a good job? [sec]
- `02-apply-stride-to-each-arrow` Apply STRIDE to each arrow: Spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege. [sec]
- `02-know-who-your-attackers-are` Know who your attackers are: Bots, curious users, ex-staff, competitors and criminals each need different defences. [sec access]
- `02-rank-risks-and-assign-owners` Rank risks and assign owners: Likelihood times impact. Fix the top risks by design and write down the ones you accept. [sec]

### Secure development process

- `02-adopt-a-secure-development-framework` Adopt a secure development framework: NIST SSDF or OWASP SAMM gives you a checklist for the whole lifecycle. [sec]
- `02-make-security-part-of-done` Make security part of ‘done’: No feature ships without review, tests and a security check. [sec]
- `02-name-a-security-owner` Name a security owner: One person is accountable for security decisions, even part-time. [sec access]

### Project setup

- `02-choose-a-home-for-tasks-and-docs` Choose a home for tasks and docs: One place for tasks, decisions and runbooks.
- `02-record-architecture-decisions` Record architecture decisions: Short ADRs explain why you chose a host, database or login provider.
- `02-pick-a-release-rhythm` Pick a release rhythm: Small, frequent releases are easier to test, review and roll back.

## 03 Resources & accounts

Gather people, tools and accounts, and lock every account down before it holds anything valuable.

### People & ownership

- `03-decide-build-hire-or-no-code` Decide: build, hire or no-code: Founder-built, agency, freelancers or no-code. Each changes who holds the keys. [access]
- `03-get-ip-and-confidentiality-in-writing` Get IP and confidentiality in writing: Code, designs and accounts belong to the company, not the contractor. [access]
- `03-plan-onboarding-and-offboarding` Plan onboarding and offboarding: A checklist for granting and revoking access, written before the first hire. [access leak]

### Lock down accounts

- `03-use-a-team-password-manager` Use a team password manager: Unique generated passwords and shared vaults. No passwords in chat, email or docs. [MUST access leak]
- `03-turn-on-strong-mfa-everywhere` Turn on strong MFA everywhere: Security keys or passkeys for email, cloud, code host, domain registrar and app stores. [MUST access]
- `03-use-company-owned-accounts-only` Use company-owned accounts only: Register cloud, domain, stores and email to the company, never a personal login. [MUST access]
- `03-create-a-break-glass-account` Create a break-glass account: One emergency admin login protected by a hardware key, stored sealed and monitored. [access]
- `03-secure-every-work-device` Secure every work device: Disk encryption, automatic updates, screen lock and a current browser on each laptop. [MUST sec leak]

### Domain & email

- `03-register-your-domain-securely` Register your domain securely: Registrar lock, MFA and auto-renew on. An expired domain can be taken over. [MUST sec]
- `03-set-up-spf-dkim-and-dmarc` Set up SPF, DKIM and DMARC: Stops others sending email that looks like it came from you. [sec leak]
- `03-turn-on-dnssec` Turn on DNSSEC: Protects your DNS records from being forged. [sec]
- `03-create-security-and-support` Create security@ and support@: Role inboxes that survive staff changes and can receive vulnerability reports. [sec]

### Tools & budget

- `03-set-up-your-code-host` Set up your code host: GitHub or GitLab organisation with MFA required and no more than two owners. [access]
- `03-claim-startup-credits` Claim startup credits: Cloud providers give free credits to new companies.
- `03-set-billing-alerts-and-spend-caps` Set billing alerts and spend caps: A leaked key often shows up first as a surprise bill. [sec leak]
- `03-keep-an-inventory-of-every-service` Keep an inventory of every service: One list of every tool and account: owner, purpose, what data it holds. [data access]

## 04 Architecture & stack

Choose boring, well-supported building blocks, and design so that one failure can't expose everything.

### Principles

- `04-prefer-managed-boring-tech` Prefer managed, boring tech: Popular frameworks and managed services get patched faster than anything custom. [sec]
- `04-follow-the-twelve-factor-app` Follow the Twelve-Factor App: Config in the environment, stateless processes, disposable servers.
- `04-read-a-cloud-security-pillar` Read a cloud security pillar: Free, vendor-written checklists for secure cloud design. [sec]
- `04-keep-the-attack-surface-small` Keep the attack surface small: Fewer services, ports, packages and admin screens mean fewer ways in. [sec leak]

### Choose the stack

- `04-frontend-framework` Frontend framework: Next.js, Nuxt or SvelteKit for web; Flutter or React Native for mobile.
- `04-backend-and-api-style` Backend and API style: REST or GraphQL on a mainstream framework, or a backend-as-a-service. [sec]
- `04-database-type` Database type: PostgreSQL fits most apps: constraints, transactions and row-level security built in. [data]
- `04-backend-as-a-service-carefully` Backend-as-a-service, carefully: Supabase, Firebase or Appwrite are fast, but their security rules become your firewall. [data access]

### Design for containment

- `04-separate-dev-staging-and-production` Separate dev, staging and production: Different accounts, databases and keys. Staging never holds real customer data. [MUST access leak]
- `04-keep-the-database-on-a-private-network` Keep the database on a private network: No public IP on the database. Only the app servers can reach it. [MUST sec data]
- `04-split-admin-from-the-public-app` Split admin from the public app: Admin tools on their own domain, behind SSO and a zero-trust proxy. [sec access]
- `04-isolate-each-customer-s-data` Isolate each customer's data: Every query is scoped to the account or organisation, enforced in the database where possible. [data access]
- `04-plan-for-failure` Plan for failure: Health checks, retries, timeouts and a second availability zone for anything critical.

### Document it

- `04-draw-the-architecture-c4` Draw the architecture (C4): Context, containers, components. Mark where data is stored and which links are encrypted. [data]
- `04-map-every-third-party` Map every third party: List each vendor that receives data: what it gets, why, and where it stores it. [data leak]
- `04-learn-system-design-basics` Learn system design basics: Caching, queues, replication and failure modes, explained with diagrams.

## 05 Data storage & privacy

Decide what you collect, where it lives, how it's encrypted, who can read it and when it's deleted.

### Classify & minimise

- `05-build-a-data-inventory` Build a data inventory: A table of every field: what, why, where stored, who can read it, how long it's kept. [MUST data]
- `05-assign-sensitivity-tiers` Assign sensitivity tiers: Public, Internal, Confidential, Restricted. Controls get stricter with each tier. [data]
- `05-collect-the-minimum` Collect the minimum: Year of birth instead of birth date; city instead of street address. [data leak]
- `05-pseudonymise-analytics-and-logs` Pseudonymise analytics and logs: Random IDs instead of emails or names wherever a person doesn't need to be identified. [data leak]

### Where data lives

- `05-choose-the-data-region-on-purpose` Choose the data region on purpose: Host where your users are and where the law expects, e.g. EU users in the EU. [MUST data]
- `05-use-a-managed-database` Use a managed database: Managed Postgres handles patching, backups and encryption at rest for you. [data]
- `05-put-files-in-object-storage` Put files in object storage: User uploads go to S3-compatible storage, never to the web server's disk. [data]
- `05-block-public-bucket-access` Block public bucket access: Turn on account-wide ‘block public access’. Share private files with short-lived signed URLs. [MUST data leak]
- `05-never-store-card-numbers` Never store card numbers: Let Stripe or another processor hold card data. You keep only a token. [MUST data leak]

### Encryption

- `05-encrypt-in-transit-everywhere` Encrypt in transit everywhere: HTTPS only, TLS 1.2 or newer, HSTS, and TLS between the app and its database too. [MUST sec data]
- `05-encrypt-at-rest-with-managed-keys` Encrypt at rest with managed keys: Disk, database and backup encryption on, with keys held in a cloud key service. [MUST data]
- `05-encrypt-the-most-sensitive-fields` Encrypt the most sensitive fields: Encrypt IDs, health data or tokens in the app, so a stolen database dump is useless. [sec data]
- `05-hash-passwords-properly` Hash passwords properly: Argon2id, scrypt or bcrypt. Never store, encrypt or log plain passwords. [MUST sec data]
- `05-plan-key-rotation` Plan key rotation: Know how to rotate every key and secret without downtime, and do it on a schedule. [sec data]

### Who can read the data

- `05-use-least-privilege-database-roles` Use least-privilege database roles: The app's database user can't drop tables. Migrations run as a separate role. [MUST data access]
- `05-turn-on-row-level-security` Turn on row-level security: The database itself makes sure each user only sees their own rows. [data access leak]
- `05-lock-down-baas-security-rules` Lock down BaaS security rules: Firebase and Supabase projects can start wide open. Write and test rules before launch. [MUST access leak]
- `05-return-only-the-fields-needed` Return only the fields needed: API responses use an explicit list of fields, never the whole database row. [data leak]

### Keep, back up, delete

- `05-set-retention-periods` Set retention periods: Each data type gets a lifespan; a scheduled job deletes or anonymises it on time. [data leak]
- `05-let-users-export-and-delete` Let users export and delete: Download my data, delete my account, and make backups age the deleted data out. [MUST data]
- `05-back-up-with-the-3-2-1-rule` Back up with the 3-2-1 rule: 3 copies, 2 kinds of storage, 1 off-site in a separate account. Encrypted and automatic. [MUST data]
- `05-test-a-restore-every-quarter` Test a restore every quarter: A backup you've never restored is a hope, not a backup. [data]
- `05-use-fake-data-outside-production` Use fake data outside production: Seed dev and staging with generated data. Never copy production down. [data leak]

## 06 Identity & access

Who can sign in, what each person and machine is allowed to do, and how you prove it.

### User sign-in

- `06-use-a-proven-login-provider` Use a proven login provider: Don't build sign-in from scratch. Use a maintained service or framework. [MUST sec access]
- `06-offer-passkeys-and-mfa` Offer passkeys and MFA: Passkeys resist phishing. Authenticator apps as a fallback; SMS only as a last resort. [sec access]
- `06-follow-modern-password-rules` Follow modern password rules: Allow long passphrases, block known-breached passwords, no forced expiry. [sec]
- `06-make-recovery-as-strong-as-login` Make recovery as strong as login: Reset and email-change flows are the most attacked. Use single-use, expiring tokens. [MUST sec]
- `06-don-t-reveal-which-emails-exist` Don't reveal which emails exist: Same response for “wrong password” and “no such account”, on login, sign-up and reset. [leak]

### Sessions & tokens

- `06-keep-sessions-in-secure-cookies` Keep sessions in secure cookies: HttpOnly, Secure, SameSite cookies, not tokens in localStorage. [sec leak]
- `06-keep-tokens-short-lived` Keep tokens short-lived: Access tokens last minutes, refresh tokens rotate, every session can be revoked. [sec]
- `06-validate-tokens-strictly` Validate tokens strictly: Check signature, algorithm, issuer, audience and expiry on every request. [sec]
- `06-let-users-see-and-end-sessions` Let users see and end sessions: A device list with “sign out everywhere”. End all sessions when the password changes. [sec access]

### Permissions (who can do what)

- `06-check-permission-on-every-request` Check permission on every request: On the server, for every endpoint and every object. Hiding a button isn't security. [MUST access leak]
- `06-model-roles-and-permissions` Model roles and permissions: Start with simple roles; add attribute or relationship rules when you need them. [access]
- `06-use-unguessable-ids-in-urls` Use unguessable IDs in URLs: Random IDs make scraping harder, but never replace permission checks. [access leak]
- `06-ask-again-before-risky-actions` Ask again before risky actions: Re-check password or passkey before changing email, payout details or deleting data. [sec access]

### Team & admin access

- `06-grant-least-privilege` Grant least privilege: Each person gets the minimum access for their job. Production access is the exception. [MUST access]
- `06-use-single-sign-on-for-internal-tools` Use single sign-on for internal tools: One identity per person, MFA enforced centrally, one switch to revoke everything. [access]
- `06-give-production-access-just-in-time` Give production access just in time: Time-limited, approved and logged access instead of standing admin rights. [sec access]
- `06-build-an-audited-admin-panel` Build an audited admin panel: Support works through a tool that masks data and records who viewed what. [data access leak]
- `06-offboard-within-hours` Offboard within hours: A checklist that removes SSO, keys, repos, cloud and vendor access the same day. [MUST access leak]
- `06-review-access-every-quarter` Review access every quarter: Owners confirm each person, key and integration still needs what it has. [access]

### Machine identities

- `06-no-long-lived-cloud-keys` No long-lived cloud keys: Use workload identity or OIDC so servers and CI get short-lived credentials. [access leak]
- `06-one-identity-per-service` One identity per service: Each service, job and integration has its own narrowly scoped credential. [access]
- `06-review-connected-oauth-apps` Review connected OAuth apps: Check which third-party apps can read your GitHub, Google Workspace or Slack. [access leak]

## 07 Build securely

Write code that resists the common attacks, and keep secrets and dependencies under control.

### Secure coding

- `07-learn-the-owasp-top-10` Learn the OWASP Top 10: The most common web risks, from broken access control to injection and misconfiguration. [sec]
- `07-validate-every-input-on-the-server` Validate every input on the server: Check the shape of every request body, parameter and header. Reject the unexpected. [MUST sec]
- `07-use-parameterised-queries` Use parameterised queries: Use an ORM or prepared statements. Never build SQL by gluing strings together. [MUST sec]
- `07-escape-output-avoid-raw-html` Escape output; avoid raw HTML: Let the framework escape. Clean any user-supplied HTML with DOMPurify. [sec]
- `07-handle-file-uploads-safely` Handle file uploads safely: Check type and size, rename files, store outside the web root, scan for malware. [sec]
- `07-block-server-side-request-forgery` Block server-side request forgery: When the server fetches a URL, allow only known destinations and block internal IPs. [sec leak]
- `07-fail-safely` Fail safely: Plain error messages for users, details only in logs. No stack traces in production. [sec leak]

### Secrets

- `07-keep-secrets-out-of-code` Keep secrets out of code: No keys in git, the frontend bundle or container images. Load them at runtime. [MUST leak]
- `07-turn-on-secret-scanning` Turn on secret scanning: Push protection blocks commits containing keys before they reach the repository. [MUST leak]
- `07-know-which-keys-may-be-public` Know which keys may be public: Publishable keys can ship to the browser. Secret and service-role keys never can. [MUST leak]
- `07-rotate-leaked-secrets-at-once` Rotate leaked secrets at once: Deleting the commit isn't enough; history and forks keep it. Revoke, then replace. [leak]
- `07-ignore-env-files-from-day-one` Ignore .env files from day one: Add .env to .gitignore and run a secret scanner before every commit. [leak]

### Dependencies & supply chain

- `07-automate-dependency-updates` Automate dependency updates: Dependabot or Renovate opens update PRs; merge them every week. [MUST sec]
- `07-scan-for-known-vulnerabilities` Scan for known vulnerabilities: Fail the build on critical issues in packages and container images. [sec]
- `07-vet-new-packages-before-adding` Vet new packages before adding: Check popularity, maintainers, install scripts and look-alike names. [sec]
- `07-commit-lockfiles-pin-versions` Commit lockfiles, pin versions: Reproducible installs (npm ci or equivalent) so builds can't change silently. [sec]
- `07-generate-a-software-bill-of-materials` Generate a software bill of materials: An SBOM answers “are we affected?” in minutes when a new flaw is announced. [sec]

### Code review & repo

- `07-protect-the-main-branch` Protect the main branch: Require pull requests, reviews and passing checks. No force-pushes. [MUST access]
- `07-run-static-analysis-on-every-pr` Run static analysis on every PR: Semgrep or CodeQL flags injection, unsafe APIs and hard-coded secrets. [sec]
- `07-double-review-sensitive-changes` Double-review sensitive changes: Changes to login, payments, permissions or crypto get a second reviewer. [sec access]
- `07-sign-commits-and-releases` Sign commits and releases: Proves who wrote the code and that builds weren't tampered with. [sec]

### AI features & AI-written code

- `07-review-ai-generated-code` Review AI-generated code: Treat it like a new hire's PR: check permissions, validation and every new package. [MUST sec]
- `07-defend-against-prompt-injection` Defend against prompt injection: Treat model output as untrusted. Never let it run tools or queries unchecked. [sec]
- `07-limit-data-sent-to-ai-providers` Limit data sent to AI providers: Send the minimum, strip personal data, choose no-training and zero-retention options. [data leak]
- `07-set-rules-for-staff-ai-use` Set rules for staff AI use: Approved tools only, on business terms that exclude training on your data. [data leak]

## 08 Test & attack it

Try to break your own app before someone else does.

### Automated tests

- `08-unit-and-integration-tests` Unit and integration tests: Cover the business rules, and above all the permission checks. [sec]
- `08-write-user-a-vs-user-b-tests` Write ‘user A vs user B’ tests: For each endpoint: user A must not read, change or delete user B's data. [MUST access leak]
- `08-end-to-end-tests-for-key-flows` End-to-end tests for key flows: Sign up, log in, reset password, pay, delete account.
- `08-load-and-flood-testing` Load and flood testing: See how the app behaves under traffic spikes and floods of requests. [sec]

### Security scanning

- `08-scan-the-running-app-dast` Scan the running app (DAST): ZAP crawls staging and probes for common flaws automatically. [sec]
- `08-scan-infrastructure-code` Scan infrastructure code: Catch public buckets and open databases before they are deployed. [sec leak]
- `08-scan-container-images` Scan container images: Use minimal base images and scan them on every build. [sec]
- `08-fuzz-your-parsers-and-inputs` Fuzz your parsers and inputs: Throw random and malformed input at file parsers, APIs and forms. [sec]

### Manual testing

- `08-follow-the-owasp-testing-guide` Follow the OWASP testing guide: A structured list of what to try: login, sessions, input, business logic. [sec]
- `08-learn-to-attack-your-own-app` Learn to attack your own app: Free hands-on labs teach the techniques real attackers use. [sec]
- `08-test-business-logic-abuse` Test business-logic abuse: Negative quantities, skipped steps, reused coupons, double-clicks and race conditions. [sec]
- `08-test-mobile-builds` Test mobile builds: Check on-device storage, logs, certificate handling and how easy the app is to unpack. [sec leak]

### Outside eyes

- `08-get-a-penetration-test-before-launch` Get a penetration test before launch: An independent tester finds what your team can't see. [MUST sec]
- `08-publish-a-security-txt` Publish a security.txt: Tells researchers how to report vulnerabilities to you. [sec]
- `08-consider-a-bug-bounty-later` Consider a bug bounty later: Once the basics are solid, pay researchers for what they find. [sec]

## 09 Where to host

Pick hosting that fits your skills, budget, data-region needs and compliance. Simple beats clever.

### Before you choose

- `09-know-the-shared-responsibility-model` Know the shared responsibility model: The host secures the hardware. You secure the configuration, code, data and access. [MUST sec]
- `09-check-certifications-and-a-dpa` Check certifications and a DPA: SOC 2 or ISO 27001 reports and a signed data processing agreement from every host. [data]
- `09-pin-every-data-region` Pin every data region: Choose the region for compute, database, backups and logs explicitly. [data]
- `09-match-the-host-to-your-team` Match the host to your team: No ops team? Use a platform that patches servers for you. Fewer moving parts, fewer mistakes. [sec]

### Websites & frontends

- `09-vercel` Vercel: Next.js-first hosting with preview deploys, a global edge and serverless functions.
- `09-netlify` Netlify: Static sites and frontend apps with functions, forms and previews.
- `09-cloudflare-workers-pages` Cloudflare Workers & Pages: Edge hosting with built-in DDoS protection and a generous free tier.
- `09-protect-preview-links` Protect preview links: Preview URLs are often public and talk to real APIs. Put them behind a password or SSO. [access leak]

### App platforms (easiest)

- `09-render` Render: Web services, workers, cron jobs and managed Postgres with private networking.
- `09-railway` Railway: Fast deploys from Git, with databases one click away.
- `09-fly-io` Fly.io: Run containers close to your users, in regions you pick.
- `09-google-cloud-run` Google Cloud Run: Serverless containers that scale to zero, with Google's IAM built in.
- `09-digitalocean-app-platform` DigitalOcean App Platform: A simple platform with managed databases and predictable pricing.

### Full cloud (most control)

- `09-aws` AWS: The widest range of services; strongest option for compliance-heavy apps.
- `09-google-cloud` Google Cloud: Strong data and AI services, Cloud Run and Kubernetes (GKE).
- `09-microsoft-azure` Microsoft Azure: The natural fit if you already live in Microsoft 365 and Entra ID.
- `09-use-one-account-per-environment` Use one account per environment: An AWS Organization or GCP folders, with production isolated from everything else. [MUST access]

### EU, VPS & self-hosting

- `09-hetzner` Hetzner: Low-cost servers in Germany and Finland for EU data residency. [data]
- `09-scaleway-and-ovhcloud` Scaleway and OVHcloud: European clouds with managed databases and EU-only regions. [data]
- `09-self-host-a-deploy-platform` Self-host a deploy platform: Coolify, Dokku or Kamal give push-to-deploy on your own server.
- `09-harden-any-server-you-run` Harden any server you run: SSH keys only, firewall on, automatic security updates, no root login. [MUST sec]

### Mobile, services & edge

- `09-app-store-accounts` App store accounts: Apple Developer and Google Play Console, registered to the company. [access]
- `09-backend-as-a-service` Backend-as-a-service: Supabase, Firebase, Convex or PocketBase for login, data and files in one place.
- `09-put-a-cdn-and-firewall-in-front` Put a CDN and firewall in front: DDoS protection, caching, TLS and a web application firewall at the edge. [sec]
- `09-transactional-email-service` Transactional email service: Password resets and receipts need good delivery and DKIM signing.

## 10 Deploy pipeline

Every change reaches production the same way: reviewed, automated, tested and reversible.

### CI/CD

- `10-automate-build-test-and-deploy` Automate build, test and deploy: Every merge runs the same pipeline. Nobody deploys from a laptop. [sec access]
- `10-harden-the-pipeline-itself` Harden the pipeline itself: Pin third-party actions to commit SHAs, use least-privilege tokens, no secrets for fork PRs. [sec leak]
- `10-deploy-with-oidc-not-stored-keys` Deploy with OIDC, not stored keys: CI swaps a short-lived token for a deploy role. No cloud keys saved in CI. [access leak]
- `10-add-security-gates` Add security gates: Tests, static analysis, dependency and secret scans must pass before deploy. [MUST sec]
- `10-require-approval-for-production` Require approval for production: Protected environments with named approvers. [access]

### Infrastructure as code

- `10-define-infrastructure-in-code` Define infrastructure in code: Terraform, OpenTofu or Pulumi: reviewed, versioned and repeatable. [sec]
- `10-protect-the-state-file` Protect the state file: Infrastructure state often contains secrets. Store it encrypted, with locked-down access. [access leak]
- `10-detect-drift` Detect drift: Get alerted when someone changes production by hand. [sec]

### Release safely

- `10-use-feature-flags` Use feature flags: Ship code switched off, turn it on for a few users, switch it off instantly.
- `10-canary-or-blue-green-deploys` Canary or blue-green deploys: Send a small share of traffic to the new version first, then the rest.
- `10-keep-one-click-rollback` Keep one-click rollback: Any release can be reverted in minutes. [sec]
- `10-migrate-databases-safely` Migrate databases safely: Expand, migrate, then contract. Back up first; never destroy data in one step. [data]

### Containers

- `10-minimal-non-root-images` Minimal, non-root images: Small base images, run as a normal user, read-only file system. [sec]
- `10-never-bake-secrets-into-images` Never bake secrets into images: Image layers keep everything forever. Inject secrets at runtime. [leak]
- `10-sign-and-verify-images` Sign and verify images: Only run images your own pipeline built and signed. [sec]

## 11 Legal & compliance

Write down what you do with data, sign the right contracts and meet the rules for your market.

### What users see

- `11-privacy-policy` Privacy policy: What you collect, why, who you share it with, how long you keep it, and users' rights. [MUST data]
- `11-terms-of-service` Terms of service: Acceptable use, limits of liability, how accounts can be closed. [MUST]
- `11-cookie-consent-where-required` Cookie consent where required: Non-essential cookies and trackers need opt-in consent in the EU and UK. [data]
- `11-app-store-privacy-labels` App store privacy labels: Apple's privacy details and Google Play's Data safety form must match reality. [data]

### Privacy law

- `11-gdpr-and-uk-gdpr-basics` GDPR and UK GDPR basics: Lawful basis, minimisation, user rights, and 72 hours to report a breach. [data]
- `11-us-state-privacy-laws` US state privacy laws: CCPA/CPRA and similar laws give rights to know, delete and opt out of sale. [data]
- `11-assess-high-risk-processing` Assess high-risk processing: A data protection impact assessment (DPIA) for sensitive data or large-scale tracking. [data]
- `11-answer-data-requests-on-time` Answer data requests on time: A simple process to handle access and deletion requests within one month. [data]

### Vendors & contracts

- `11-sign-a-dpa-with-every-processor` Sign a DPA with every processor: Hosting, email, analytics, support and AI vendors all need one. [MUST data]
- `11-publish-a-sub-processor-list` Publish a sub-processor list: Who processes data on your behalf, and where. Business customers will ask. [data]
- `11-check-vendor-security` Check vendor security: Ask for SOC 2 or ISO reports; prefer vendors with SSO and audit logs. [data access]

### Standards & industry rules

- `11-soc-2-or-iso-27001-for-b2b` SOC 2 or ISO 27001 for B2B: Business buyers often require one. Compliance tools make it manageable. [sec]
- `11-industry-specific-rules` Industry-specific rules: PCI DSS for cards, HIPAA for US health, DORA for EU finance, COPPA for children. [data]
- `11-eu-cyber-resilience-act` EU Cyber Resilience Act: Security and vulnerability-reporting duties for software sold in the EU, phasing in 2026–2027. [sec]
- `11-eu-ai-act-for-ai-features` EU AI Act for AI features: Transparency duties for chatbots and generated content; stricter rules for high-risk uses.
- `11-accessibility-law` Accessibility law: The European Accessibility Act has covered many consumer apps since June 2025.

## 12 Launch hardening

The final pre-flight checklist. Finish it before real users and real data arrive.

### Web protections

- `12-set-security-headers` Set security headers: CSP, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, frame-ancestors. [MUST sec]
- `12-score-an-a-on-tls` Score an A on TLS: Test your TLS setup and certificate chain, then consider HSTS preload. [sec]
- `12-configure-cors-tightly` Configure CORS tightly: Allow only your own origins. Never echo back any origin when credentials are allowed. [sec leak]
- `12-defend-against-csrf` Defend against CSRF: SameSite cookies plus CSRF tokens on every request that changes something. [sec]

### Abuse protection

- `12-rate-limit-everything-public` Rate-limit everything public: Login, sign-up, reset, search, API and AI endpoints, per IP and per account. [MUST sec]
- `12-turn-on-a-waf-and-ddos-protection` Turn on a WAF and DDoS protection: Managed firewall rules block common attacks before they reach you. [sec]
- `12-stop-bots-at-sign-up` Stop bots at sign-up: Invisible challenges block fake accounts and password-stuffing. [sec]
- `12-cap-spend-on-paid-apis` Cap spend on paid APIs: Quotas on SMS, email and AI calls stop ‘denial of wallet’ attacks. [sec]

### Remove what leaks

- `12-turn-off-debug-mode` Turn off debug mode: No verbose errors, debug toolbars or public source maps in production. [MUST leak]
- `12-close-dev-paths-and-endpoints` Close dev paths and endpoints: Block /.git, /.env, test routes, open API docs and default admin pages. [MUST leak]
- `12-check-search-engine-indexing` Check search engine indexing: Private pages stay behind login and marked noindex. Nothing sensitive in sitemaps. [leak]
- `12-delete-test-accounts-and-defaults` Delete test accounts and defaults: Remove seed users and change every password that was ever shared. [MUST access leak]
- `12-check-for-subdomain-takeover` Check for subdomain takeover: Delete DNS records that point at services you no longer use. [sec]

### Go / no-go

- `12-run-the-launch-checklist` Run the launch checklist: Pentest criticals fixed, a backup restored, alerts tested, someone on call. [MUST]
- `12-have-the-incident-plan-ready` Have the incident plan ready: Who to call, how to switch things off, how to tell users. See step 14. [MUST]
- `12-set-up-a-status-page` Set up a status page: Tell users about problems before they have to tell you.
- `12-launch-in-stages` Launch in stages: Invite-only or a waitlist first. Watch the numbers, then open up.

## 13 Monitor & detect

You can't respond to what you can't see. Log the right things, and never log secrets.

### Logging

- `13-log-security-events` Log security events: Logins, failures, permission denials, admin actions, exports and key changes. [MUST sec]
- `13-never-log-secrets-or-personal-data` Never log secrets or personal data: Redact tokens, passwords, card numbers and personal fields before they're written. [MUST data leak]
- `13-centralise-and-protect-logs` Centralise and protect logs: Ship logs off the server; append-only, access-controlled, kept 90 days or more. [data access]
- `13-turn-on-cloud-audit-trails` Turn on cloud audit trails: Record every console and API action in your cloud accounts. [access]

### Monitoring

- `13-track-errors-with-scrubbing-on` Track errors, with scrubbing on: Catch crashes with stack traces, with personal-data scrubbing enabled. [leak]
- `13-uptime-checks-from-outside` Uptime checks from outside: External checks every minute from several regions.
- `13-metrics-and-tracing` Metrics and tracing: Know what normal looks like so you can spot abnormal.
- `13-use-privacy-friendly-analytics` Use privacy-friendly analytics: Cookieless or EU-hosted analytics. Mask form inputs in session replay. [data leak]

### Detection & alerts

- `13-alert-on-suspicious-activity` Alert on suspicious activity: Login spikes, mass exports, new admin users, sign-ins from new countries. [MUST sec]
- `13-use-cloud-threat-detection` Use cloud threat detection: Managed detectors flag leaked keys, crypto-mining and odd API use. [sec]
- `13-plant-canary-tokens` Plant canary tokens: Fake keys and records that alert you the moment someone uses them. [sec leak]
- `13-watch-for-breached-accounts` Watch for breached accounts: Get told when accounts on your domain appear in breach dumps. [leak]
- `13-make-sure-a-human-sees-alerts` Make sure a human sees alerts: An on-call rota, paging, and alerts someone actually reads.

## 14 Incidents & recovery

Assume something will go wrong. Decide now how you'll contain it, recover and tell people.

### Prepare

- `14-write-an-incident-response-plan` Write an incident response plan: Roles, severity levels, contacts, first steps and message templates. [MUST sec]
- `14-keep-an-offline-contact-sheet` Keep an offline contact sheet: Phone numbers for the team, host, lawyer and insurer, usable even if email is down.
- `14-build-kill-switches` Build kill switches: One step to disable sign-ups, a feature, an API key or every session. [sec]
- `14-rehearse-once-a-year` Rehearse once a year: Walk through “our database leaked” as a tabletop exercise. [sec]
- `14-consider-cyber-insurance` Consider cyber insurance: Can cover forensics, notification costs and legal advice.

### Respond

- `14-contain-first` Contain first: Revoke keys, block access, isolate systems. Preserve evidence before wiping anything. [sec]
- `14-rotate-everything-that-may-be-exposed` Rotate everything that may be exposed: Assume anything the attacker could reach is compromised. [access leak]
- `14-notify-within-the-legal-deadline` Notify within the legal deadline: GDPR: the regulator within 72 hours; affected users without undue delay if risk is high. [MUST data]
- `14-communicate-honestly` Communicate honestly: What happened, which data, what you're doing, and what users should do now.

### Recover & learn

- `14-restore-from-clean-backups` Restore from clean backups: Know which backup predates the compromise; restore onto fresh infrastructure. [data]
- `14-test-your-recovery-targets` Test your recovery targets: Prove you can meet your RTO and RPO with a real restore drill. [data]
- `14-run-blameless-postmortems` Run blameless postmortems: Find causes in systems, not people, and track every fix to done.
- `14-feed-lessons-back-in` Feed lessons back in: Each incident updates the threat model, tests and runbooks. [sec]

## 15 Update & maintain

Shipping is the start. Keep dependencies, platforms, access and data healthy for the app's whole life.

### Routine updates

- `15-patch-on-a-schedule` Patch on a schedule: Merge dependency updates weekly; fix actively exploited flaws within 48 hours. [MUST sec]
- `15-track-end-of-life-dates` Track end-of-life dates: Upgrade Node, Python, databases and operating systems before support ends. [sec]
- `15-version-releases-clearly` Version releases clearly: Semantic version numbers and a changelog people can read.
- `15-automate-release-notes` Automate release notes: Conventional commit messages let tools write changelogs and bump versions.

### Every release

- `15-loop-back-through-steps-07-10` Loop back through steps 07–10: Each release gets review, scans, tests and a staged rollout again. [sec]
- `15-revisit-the-threat-model` Revisit the threat model: New data, new roles or a new integration? Go back to step 02 for that feature. [sec]
- `15-mobile-staged-rollouts` Mobile: staged rollouts: Release to a share of users first; force an update for versions with security bugs.
- `15-over-the-air-fixes-for-mobile` Over-the-air fixes for mobile: Ship JavaScript and asset fixes without a store review, within store rules.

### Ongoing hygiene

- `15-review-access-every-quarter` Review access every quarter: Remove people, keys and integrations that no longer need access. [MUST access]
- `15-rotate-keys-and-secrets` Rotate keys and secrets: On a schedule, and whenever someone with access leaves. [access leak]
- `15-confirm-deletion-jobs-run` Confirm deletion jobs run: Check old data is actually being deleted, including from backups. [data leak]
- `15-yearly-pentest-and-restore-drill` Yearly pentest and restore drill: Retest after big changes; restore a full backup into a clean account. [sec data]
- `15-prune-vendors-and-services` Prune vendors and services: Every unused service is attack surface and another copy of your data. [data leak]

### Scale & retire

- `15-scale-without-weakening-security` Scale without weakening security: New regions, replicas and caches get the same encryption, access rules and logging. [sec data]
- `15-retire-features-cleanly` Retire features cleanly: Delete their data, endpoints, flags, keys and DNS records. [data leak]
- `15-shut-down-responsibly` Shut down responsibly: Warn users, offer export, delete data and backups, and keep the domain registered. [data leak]
