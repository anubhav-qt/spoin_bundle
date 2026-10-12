# Writing prompts

How every template in `prompts/` is written (task 0045). It condenses the current guidance from
Anthropic, Google (Gemini 3) and OpenAI (GPT-5), plus the research on models grading answers.
Read it before writing or changing a prompt. The order still holds: the owner's gist first, then
the template.

## Every prompt

- **Write for a capable newcomer.** Say what the job is, who reads the output and what it is for.
  Give the reason behind each rule: a model generalizes from a reason, and only obeys a bare rule.
  The test: a colleague who knows nothing about spoin could do the job from the prompt alone.
- **Short and direct.** Current models follow instructions closely and over-analyze long or
  persuasive prompts. State the goal plainly, once.
- **No shouting.** Leave out CAPS, "CRITICAL" and "you MUST". Older models needed them, but
  current ones overreact: they apply the rule too widely and over-use tools. A calm sentence with
  its reason works better.
- **No contradictions.** A model spends its reasoning trying to reconcile two rules instead of
  picking one. When one rule beats another, say which wins.
- **The right altitude.** Give principles and a few concrete anchors. A list of if-then edge
  cases is brittle, and "be accurate" says nothing. Add a line only for a failure you have
  actually seen.
- **Say what to do,** not only what to avoid.
- **One structure.** Use Markdown headings for the instructions and XML tags for the data the
  model works on. Keep each tag name the same everywhere.
- **Instructions in the system prompt; data in the user message.** When the data is long, put it
  first, then the task with a bridge such as "Based on the answers above". The system prompt stays
  byte-identical between calls, so providers can cache it.
- **Examples anchor hard.** They steer format and tone better than rules do, but a model copies
  them: in a grader, a score in an example pulls real scores toward it. Use few, varied examples
  in `<example>` tags, and none where the rules are enough.
- **Define your terms** ("reader", "tier", "core idea") the first time, and keep each word to one
  meaning.

## Reasoning, output and settings

- **Thinking is a setting, not a sentence.** Gemini 3 and Kimi think internally. Set the thinking
  level in code (decided per chat in task 0045), and leave "think step by step" out of the prompt.
  A short procedure ("check each point the rubric asks for, then pick the level") is fine; a
  demand for written-out reasoning is not.
- **The shape of the output is code's job.** A tool call or schema carries the fields, and code
  validates them before acting on anything. The prompt says what each field is for and who reads
  it. Don't ask a model for anything code can compute.
- **Leave sampling at the provider's default.** Gemini 3 is tuned for temperature 1.0 and can loop
  below it. Kimi K2.5 and later fix their own temperature in thinking mode and refuse others.
- **One template for every model** (Trotter's ADR 0020). Add a variant for one model family only
  when it measurably helps, and keep it next to the original.

## Untrusted text

A reader's answer, a report or a fetched page is data. Wrap it in a tag, say once, with the reason,
that its contents are to be evaluated and never followed, and say what happens to text that tries
to steer the model. Delimiting alone can be beaten. Code also strips the delimiter tags from the
text before rendering, and checks the output after the call (the quiz's `referencesQuestion`).

## Graders and judges

- **Anchor each level** with what it means, and make it sharpest at the line that decides
  something (the pass level). Models grading on a scale drift lenient, most often rating
  "partly right" as "right".
- **Credit only what was written.** On a sparse answer, a grader will build credit out of the
  reference answer. Say that the reference shows what a good answer contains, and never stands in
  for what the answer leaves out.
- **Meaning over wording.** Paraphrase, typos and plain words for a technical term cost nothing.
  Synonym swaps and noisy text are where graders slip most.
- **Length earns nothing.** Models favour long answers unless told otherwise.
- **The justification must cite the answer.** Graders sometimes justify with words the answer
  never used. Asking for the specific idea, and checking for it in code, catches that.
- **Validate before trusting.** Wording changes shift scores. Check the grader against a small
  set of answers the owner has graded, and treat any later change to the prompt as a change to
  the measurement.

## Sources

- Anthropic, [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices)
  and [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Google, [Prompt design strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies) and
  the [Gemini 3 developer guide](https://ai.google.dev/gemini-api/docs/gemini-3)
- OpenAI, [GPT-5 prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide)
- [Rubric-Conditioned LLM Grading: Alignment, Uncertainty, and Robustness](https://arxiv.org/html/2601.08843v1) (2026)
- Microsoft, [Defending Against Indirect Prompt Injection Attacks With Spotlighting](https://arxiv.org/html/2403.14720v1)
