import type {
  Api,
  AssistantMessage,
  AssistantMessageEventStream,
  Model,
  SimpleStreamOptions,
  TranscriptContext,
} from "@spoin/pi-ai";
import type { ModelCallFailure } from "@spoin/shared/enums";
import { type CallOutcome, failedMessage, type RecordCall, replay, runCall } from "./calls.ts";
import type { Rung } from "./nim.ts";

/*
 * breader's balancer (`ai/tools/balancer.ts` on origin/dev at `e3a3bce`, 2026-10-11), itself after
 * spoin's ADR-0084, as pi's stream function for a chat on NIM (task 0045). It is for NIM only;
 * Gemini calls go straight to CLIProxyAPI.
 *
 * - NVIDIA publishes no limits and sends no limit headers. The trouble is queues (minutes before
 *   the first token), "overloaded", 504s at 300 s, and outages that last hours. So every failure
 *   cools its model down, doubling with each failure in a row, and a success resets it.
 * - Every wait has random jitter (half to one and a half times as long), so calls that failed
 *   together don't all come back at the same moment.
 * - The top model is worth waiting for. A weaker one only takes a call when the top one is cooling
 *   for longer than `waitForTopS`, or has failed `strikesToFall` times in a row. Primary rungs at
 *   the top are equals, and the one with the fewest calls in flight takes the next.
 * - A model that says it isn't open to the key (401, 403, 404) is dropped for the run. A patient
 *   process (one that never ends) asks it again an hour later instead.
 * - An empty answer or a refused request (another 4xx) is about one call, not the model. That call
 *   alone waits and asks again, and after EMPTY_TRIES empty answers, or one refusal, it asks the
 *   next model on the ladder. When no model is left for it, the call fails.
 * - A call refused for asking too much is asked again on the same model for what the refusal
 *   allows, before any of the above.
 * - Every Balancer in a process shares each model's state (calls in flight, cooldown): they all
 *   call the same model with the same key.
 *
 * Each call is buffered until it ends, so a failure is retried before the chat sees it, and a
 * chat can move to Nemotron mid-run. Every try is a `model_call` row.
 */

export interface BalancerOptions {
  /** How long the top models may be cooling before a weaker one takes the call. */
  waitForTopS: number;
  /** Failures in a row before a weaker one takes the call anyway. */
  strikesToFall: number;
  /** Tries for one call before it gives up. */
  maxTries: number;
  /** A process that never ends: a model that refuses the key is asked again later, not dropped. */
  patient?: boolean;
}

export const BALANCER_DEFAULTS: BalancerOptions = { waitForTopS: 300, strikesToFall: 3, maxTries: 12 };

/** First cooldown and cap, in seconds, per kind of failure that cools a model. */
const COOL: Partial<Record<ModelCallFailure, [number, number]>> = {
  rate: [60, 1800],
  busy: [60, 900],
  slow: [30, 600],
};

/** Empty answers one call takes from a model before it asks another, and the first wait between them. */
const EMPTY_TRIES = 3;
const EMPTY_WAIT_S = 20;
/** How long a patient process leaves a model that refused the key. */
const GONE_S = 3600;

interface State {
  name: string;
  inFlight: number;
  coolUntil: number;
  strikes: number;
  /** It refused the key: off for the run, or cooling until it's asked again when patient. */
  gone: boolean;
}

/** Each model's state, by model, shared by every Balancer in the process. */
const STATES = new Map<string, State>();

/** Half to one and a half times n. */
export const jitter = (n: number) => n * (0.5 + Math.random());
/** A wait after `strikes` failures in a row: `base` doubling with each, up to `cap`, with jitter. */
export const backoffS = (strikes: number, base: number, cap: number) =>
  jitter(Math.min(cap, base * 2 ** (strikes - 1)));

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

export class Balancer {
  private readonly ladder: Rung[];
  private readonly apiKey: string;
  private readonly record: RecordCall;
  private readonly opts: BalancerOptions;
  /** The top rungs: the primary ones at the start of the ladder, or just the first. */
  private readonly top: Rung[];

  constructor(ladder: Rung[], apiKey: string, record: RecordCall, opts: BalancerOptions = BALANCER_DEFAULTS) {
    this.ladder = ladder;
    this.apiKey = apiKey;
    this.record = record;
    this.opts = opts;
    for (const rung of ladder) {
      if (!STATES.has(rung.model.id)) {
        STATES.set(rung.model.id, {
          name: rung.model.name,
          inFlight: 0,
          coolUntil: 0,
          strikes: 0,
          gone: false,
        });
      }
    }
    const lead = ladder.findIndex((rung) => !rung.primary);
    this.top = ladder.slice(0, lead < 0 ? ladder.length : Math.max(1, lead));
  }

  /** The models refusing the key, by name, until one of them answers again. */
  static refused(): string[] {
    return [...STATES.values()].filter((state) => state.gone).map((state) => state.name);
  }

  /**
   * pi-agent's stream function. The model it is handed is ignored: the ladder picks one for every
   * call. A call that never gets an answer ends in an error message, never a throw.
   */
  readonly streamFn = (_model: Model<Api>, context: TranscriptContext, options?: SimpleStreamOptions) =>
    this.stream(context, options);

  async stream(
    context: TranscriptContext,
    options: SimpleStreamOptions = {},
  ): Promise<AssistantMessageEventStream> {
    const first = this.ladder[0];
    if (!first) throw new Error("A balancer needs at least one rung.");
    try {
      return replay(await this.call(context, options));
    } catch (error) {
      return replay(failedMessage(first.model, error instanceof Error ? error.message : String(error)));
    }
  }

  private state(rung: Rung): State {
    const state = STATES.get(rung.model.id);
    if (!state) throw new Error(`No state for ${rung.model.id}.`);
    return state;
  }

  /** The rung to call now, or how long to wait before asking again. `skip`: models this call won't ask, and why. */
  private pick(now: number, skip: Map<string, string>): Rung | number {
    const usable = (rung: Rung) => !skip.has(rung.model.id) && (this.opts.patient || !this.state(rung).gone);
    const top = this.top.filter(usable);
    const rest = this.ladder.slice(this.top.length).filter(usable);
    if (!top.length && !rest.length) {
      const why = this.ladder.map((rung) => skip.get(rung.model.id) ?? `${rung.model.name} refuses the key`);
      throw new Error(`No model left to ask: ${why.join("; ")}.`);
    }

    const open = top.filter(
      (rung) => this.state(rung).coolUntil <= now && this.state(rung).inFlight < rung.maxInFlight,
    );
    if (open.length) {
      return open.reduce((a, b) => (this.state(b).inFlight < this.state(a).inFlight ? b : a));
    }
    let wait = Number.POSITIVE_INFINITY;
    let worthWaiting = false;
    for (const rung of top) {
      const state = this.state(rung);
      const cooling = Math.max(0, state.coolUntil - now);
      // Busy with other calls isn't a failure: wait for it rather than fall.
      if (!cooling) {
        wait = Math.min(wait, 5000);
        worthWaiting = true;
        continue;
      }
      wait = Math.min(wait, cooling);
      if (cooling <= this.opts.waitForTopS * 1000 && state.strikes < this.opts.strikesToFall)
        worthWaiting = true;
    }
    if (!worthWaiting) {
      for (const rung of rest) {
        const state = this.state(rung);
        const cooling = Math.max(0, state.coolUntil - now);
        if (!cooling && state.inFlight < rung.maxInFlight) return rung;
        if (!cooling) {
          wait = Math.min(wait, 5000);
          break;
        }
        wait = Math.min(wait, cooling);
      }
    }
    return Math.min(wait, 60_000);
  }

  /** Waits for a model free for this call; null when the caller gave up meanwhile. */
  private async next(skip: Map<string, string>, signal?: AbortSignal): Promise<Rung | null> {
    for (;;) {
      if (signal?.aborted) return null;
      const picked = this.pick(Date.now(), skip);
      if (typeof picked !== "number") return picked;
      await sleep(jitter(picked), signal);
    }
  }

  private cool(rung: Rung, outcome: CallOutcome) {
    const state = this.state(rung);
    if (outcome.failure === "gone") {
      state.gone = true;
      if (this.opts.patient) state.coolUntil = Date.now() + jitter(GONE_S) * 1000;
      return;
    }
    const cool = outcome.failure ? COOL[outcome.failure] : undefined;
    if (!cool) return;
    // Calls already in flight when the model started cooling fail together: that's one strike.
    if (state.coolUntil > Date.now()) return;
    state.strikes++;
    const secs = outcome.retryAfterS
      ? outcome.retryAfterS + Math.random() * 10
      : backoffS(state.strikes, cool[0], cool[1]);
    state.coolUntil = Date.now() + secs * 1000;
  }

  /** One call on the best model free, retried across the ladder until it answers. */
  private async call(context: TranscriptContext, options: SimpleStreamOptions): Promise<AssistantMessage> {
    let cuts = 0;
    const skip = new Map<string, string>();
    const empties = new Map<string, number>();
    for (let tries = 1; ; tries++) {
      const rung = await this.next(skip, options.signal);
      if (!rung) return abandoned(this.ladder);
      const state = this.state(rung);
      const name = rung.model.name;
      state.inFlight++;
      let pause = 0;
      try {
        const outcome = await this.ask(rung, context, options);
        if (outcome.abandoned) return outcome.message;
        if (outcome.failure === null) {
          state.strikes = 0;
          state.coolUntil = 0;
          state.gone = false;
          return outcome.message;
        }
        const reason = outcome.reason ?? outcome.failure;
        if (outcome.failure === "bad" || outcome.failure === "empty") {
          let why = `${name} refused it (${reason.slice(0, 120)})`;
          let refused = true;
          if (outcome.failure === "empty") {
            const n = (empties.get(rung.model.id) ?? 0) + 1;
            empties.set(rung.model.id, n);
            why = `${name} answered it empty ${n} times`;
            if (n < EMPTY_TRIES) {
              refused = false;
              pause = jitter(EMPTY_WAIT_S * 2 ** (n - 1)) * 1000;
            }
          }
          if (refused) skip.set(rung.model.id, why);
        } else if (outcome.failure === "cut") {
          cuts++;
          if (cuts >= 2) throw new Error(`${name} ran out of room twice: ${reason}`);
        } else {
          this.cool(rung, outcome);
        }
        if (tries >= this.opts.maxTries)
          throw new Error(`No answer after ${tries} tries; the last: ${name} ${reason}`);
      } finally {
        state.inFlight--;
      }
      if (pause) await sleep(pause, options.signal);
    }
  }

  /**
   * One model's answer, every try recorded. A call refused for asking too much is asked again for
   * what the refusal allows, until it asks for no less than that (breader's nim.ts).
   */
  private async ask(
    rung: Rung,
    context: TranscriptContext,
    options: SimpleStreamOptions,
  ): Promise<CallOutcome> {
    for (let maxTokens = rung.model.maxTokens; ; ) {
      // The balancer is the only one retrying: pi's own retries are off.
      const outcome = await runCall(rung.model, context, {
        ...options,
        apiKey: this.apiKey,
        maxTokens,
        maxRetries: 0,
      });
      this.record(rung.model, outcome);
      const room = outcome.room;
      if (outcome.failure !== "bad" || room === undefined || room <= 0 || room >= maxTokens) return outcome;
      maxTokens = room;
    }
  }
}

/** The answer to a call its caller gave up on while it waited for a model. */
function abandoned(ladder: Rung[]): AssistantMessage {
  const first = ladder[0];
  if (!first) throw new Error("A balancer needs at least one rung.");
  return {
    ...failedMessage(first.model, "The call was abandoned before a model took it."),
    stopReason: "aborted",
  };
}
