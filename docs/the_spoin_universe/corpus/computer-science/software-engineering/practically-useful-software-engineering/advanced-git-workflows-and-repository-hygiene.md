---
title: Advanced Git Workflows, Repository Hygiene, and Multitasking Mechanics
kind: topic_source
category: computer science
sub_category: software engineering
scope: topic
source: "Pro Git (Chacon & Straub), Git Internals Documentation, Graphite Stacked PR Architecture"
source_date: 2024
topic_tags:
  - software-engineering
  - git-workflows
  - git-worktree
  - git-bisect
  - repository-hygiene
  - stacked-prs
---
## Git Worktrees and Zero-Cost Context Switching

A pervasive productivity bottleneck for software developers is handling urgent context switches. An engineer in the middle of a complex, multi-day architectural refactor may have thirty modified files, broken intermediate builds, and uncommitted schema migrations. When a high-severity production incident demands an immediate hotfix, the traditional junior response is running `git stash`, switching to `main`, pulling, creating a hotfix branch, fixing the issue, and attempting `git stash pop`—which frequently results in messy merge conflicts and invalidated build caches.

Senior engineers utilize `git worktree` to achieve zero-cost, simultaneous branch execution. Git worktrees permit a single underlying repository (`.git` directory) to be checked out simultaneously into multiple, completely independent filesystem directories.

To handle an emergency hotfix without perturbing active refactoring work:
```bash
git worktree add ../hotfix-branch main
cd ../hotfix-branch
```
This command instantly creates a clean, sibling working tree linked to `main`. The developer switches directories, writes the hotfix, runs tests, commits, and pushes a pull request. Meanwhile, the original project directory retains all thirty uncommitted refactoring files, active language server indices, and running local development servers completely undisturbed. Once the hotfix is merged, cleaning up requires a single command:
```bash
git worktree remove ../hotfix-branch
```
Worktrees eliminate git stash contamination, prevent accidental cross-branch file leakage, and eradicate compiler rebuild delays across unrelated branches.

## Automated Regression Pinpointing via Scripted Git Bisect

When a software regression or performance degradation is discovered in a production codebase, manual inspection across hundreds of intermediate commits is tedious and error-prone. Git provides a binary search mechanism through `git bisect`, but senior engineers amplify its power by executing automated, headless bisect scripts via `git bisect run`.

The workflow begins by defining a known "bad" commit (typically the current HEAD) and a known "good" commit (such as a previous release tag):
```bash
git bisect start HEAD v2.4.0
```
Rather than manually inspecting the code, compiling, and testing each commit step by step, the engineer writes an automated test or verification script (`check_regression.sh`). The script performs the exact check and exits with standard Unix return codes:
- Exit code `0`: The current commit is "good" (the bug is absent).
- Exit code `1` through `127` (except 125): The current commit is "bad" (the regression is present).
- Exit code `125`: The current commit cannot be tested (e.g., build broken due to an unrelated syntax error), instructing Git to skip this commit.

The engineer launches the automated binary search:
```bash
git bisect run ./check_regression.sh
```
Git executes the binary search completely autonomously, checking out intermediate commits, running the script, and evaluating the exit code. Within eight to ten automated iterations across a span of 1,000 commits, Git halts, outputs the exact commit hash that introduced the regression, and displays its author, timestamp, and full diff.

## Git Rerere and Automated Conflict Resolution Memory

Long-running feature branches, continuous upstream rebasing, and complex merge operations frequently force developers to resolve the exact same merge conflict repeatedly. Resolving identical merge conflicts across rebase steps wastes engineering hours and introduces human error when an exhausted developer accidentally drops a line of code.

Git contains a built-in, highly effective engine to automate this: `rerere` ("Reuse Recorded Resolution"). When enabled globally:
```bash
git config --global rerere.enabled true
```
Git continuously monitors merge conflicts across all operations (merge, rebase, cherry-pick, revert). When a merge conflict occurs, Git records the pre-image (the conflicting hunks in both branches) and the post-image (the manual resolution applied by the developer).

If the same conflict hunks are encountered in any future rebase or merge operation—even across different branches or rebasing steps—Git recognizes the pre-image and automatically applies the recorded resolution without human intervention. Git outputs a brief notification: `Resolved 'src/core/auth.ts' using previous resolution`. Enabling `rerere` transforms multi-step rebasing from an exhausting manual chore into an automated, predictable background process.

## Interactive Rebase, Fixup Commits, and Autosquash Hygiene

High-performing engineering organizations prioritize repository commit history as a readable, bisectable architectural log. Pushing messy, disorganized commits ("wip", "fixed typo", "trying again", "debug log") degrades git blame utility and turns code review into an exhausting archaeology exercise.

Senior engineers maintain pristine commit hygiene using interactive rebasing and automated autosquash workflows:
- Fixup Commits: While developing a feature, minor bugfixes or formatting adjustments related to an earlier commit are not committed as messy separate commits. Instead, the developer stages the change and commits it as an automated fixup targeting the specific earlier commit hash:
  ```bash
  git commit --fixup <target-commit-hash>
  ```
  Git formats the commit message automatically as `fixup! <original commit subject>`.
- Interactive Autosquash: When preparing the branch for review, the developer initiates an interactive rebase with autosquash enabled:
  ```bash
  git rebase -i --autosquash origin/main
  ```
  Git parses the `fixup!` prefixes, automatically reorganizes the commit order to place each fixup immediately following its target commit, and marks it with the `fixup` command. The rebase executes automatically, seamlessly blending the corrections into the target commits while preserving the original commit messages. The resulting branch presents a clean, logical progression of atomic, fully functional commits.

## Stacked Pull Request Architecture and Atomic Feature Decomposition

A primary source of code review latency and production risk is the monolithic pull request (PR). When a developer submits a 2,500-line PR encompassing schema changes, service logic, API endpoints, and UI components, reviewers experience cognitive fatigue. Reviewers either skim the PR and approve it with superficial "LGTM" comments, missing critical edge cases, or delay review for days, causing the branch to grow stale.

Senior engineering teams decompose large features into "Stacked Pull Requests":
- The feature is split into small, dependent, atomic pull requests that build sequentially upon one another:
  1. PR 1 (Data Layer): Database migration and ORM schema definitions (~150 lines).
  2. PR 2 (Service Layer): Core domain business logic and integration tests (~300 lines).
  3. PR 3 (API Layer): HTTP controllers, validation schemas, and serialization contracts (~150 lines).
  4. PR 4 (Presentation Layer): Frontend UI views and client state integration (~250 lines).
- Reviewers can review each individual PR in ten minutes with high focus and deep architectural scrutiny.
- Tooling such as Graphite, `git-branchless`, or custom Git branch stacking workflows automate the rebasing of child branches when parent PRs receive modifications during code review. As each PR passes review, it merges down the stack, delivering continuous, low-risk progress into the main branch.
