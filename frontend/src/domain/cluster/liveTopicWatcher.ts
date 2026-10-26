import type { LiveChannel, LiveChannelStatus, TopicEvent } from "./liveChannel";
import type { SubscribeOptions } from "./liveProtocol";
import type { LiveTopicReducer } from "./liveTopics";

/**
 * Folds one topic of a live channel into a state through a reducer, for one consumer
 * (a hook instance, a store). It subscribes while it has listeners.
 */

export type LiveTopicStatus =
  /** Nothing to watch (no cluster or no topic). */
  | "idle"
  /** Subscribed, waiting for the snapshot. */
  | "waiting"
  /** Has the snapshot and follows the updates. */
  | "live"
  /** The channel is down; `data` is the last state seen, if any. */
  | "offline"
  /** The server refused the topic, or its data did not match. */
  | "error";

export interface LiveTopicState<T> {
  status: LiveTopicStatus;
  data: T | null;
  /** The last applied update's seq, 0 right after a snapshot. */
  seq: number;
  error: string | null;
}

export const IDLE_TOPIC_STATE: LiveTopicState<never> = Object.freeze({ status: "idle", data: null, seq: 0, error: null });

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export class LiveTopicWatcher<T> {
  readonly topic: string;
  private readonly channel: LiveChannel;
  private readonly reducer: LiveTopicReducer<T>;
  private readonly options: SubscribeOptions | undefined;
  private readonly listeners = new Set<() => void>();
  private state: LiveTopicState<T> = IDLE_TOPIC_STATE;
  private stop: (() => void) | null = null;

  constructor(channel: LiveChannel, topic: string, reducer: LiveTopicReducer<T>, options?: SubscribeOptions) {
    this.channel = channel;
    this.topic = topic;
    this.reducer = reducer;
    this.options = options;
  }

  /** Changes the topic's subscribe options (a simulation's speed) while it is watched. */
  configure = (options: SubscribeOptions): void => {
    this.channel.configure(this.topic, options);
  };

  getState = (): LiveTopicState<T> => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    if (this.listeners.size === 1) {
      this.start();
    }
    return () => {
      this.listeners.delete(listener);
      if (this.listeners.size === 0) {
        this.end();
      }
    };
  };

  private start(): void {
    this.set({ status: "waiting", data: null, seq: 0, error: null });
    const offStatus = this.channel.onStatusChange((status) => this.channelStatus(status));
    const offTopic = this.channel.subscribe(this.topic, (event) => this.receive(event), this.options);
    this.stop = () => {
      offTopic();
      offStatus();
    };
    this.channelStatus(this.channel.getStatus());
  }

  private end(): void {
    this.stop?.();
    this.stop = null;
    this.state = IDLE_TOPIC_STATE;
  }

  private channelStatus(status: LiveChannelStatus): void {
    if (status === "open") {
      if (this.state.status === "offline") {
        this.set({ ...this.state, status: "waiting", error: null });
      }
      return;
    }
    if (status === "connecting") {
      return;
    }
    if (this.state.status === "live" || this.state.status === "waiting") {
      this.set({ ...this.state, status: "offline" });
    }
  }

  private receive(event: TopicEvent): void {
    switch (event.type) {
      case "snapshot":
        try {
          this.set({ status: "live", data: this.reducer.snapshot(event.snapshot), seq: 0, error: null });
        } catch (error) {
          this.set({ status: "error", data: null, seq: 0, error: `unexpected snapshot of ${this.topic}: ${describe(error)}` });
        }
        return;
      case "update":
        if (this.state.status !== "live" || this.state.data === null) {
          return;
        }
        try {
          this.set({ ...this.state, data: this.reducer.update(this.state.data, event.data, event.seq), seq: event.seq });
        } catch (error) {
          this.set({ ...this.state, error: `unexpected update of ${this.topic}: ${describe(error)}` });
        }
        return;
      case "error":
        this.set({ ...this.state, status: "error", error: event.message });
        return;
    }
  }

  private set(state: LiveTopicState<T>): void {
    this.state = state;
    for (const listener of [...this.listeners]) {
      listener();
    }
  }
}
