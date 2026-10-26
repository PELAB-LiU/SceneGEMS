import type { WebSocketLike } from "../domain/cluster/liveChannel";

/**
 * A fake WebSocket for the live channel tests: records what the client sends and lets the
 * test open, feed and drop the connection.
 */
export class MockWebSocket implements WebSocketLike {
  static instances: MockWebSocket[] = [];

  readonly url: string;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  closedByClient = false;
  onopen: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  static reset(): void {
    MockWebSocket.instances = [];
  }

  static latest(): MockWebSocket {
    const socket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    if (!socket) {
      throw new Error("no socket was created");
    }
    return socket;
  }

  static factory = (url: string): WebSocketLike => new MockWebSocket(url);

  send(data: string): void {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }

  close(): void {
    this.closedByClient = true;
    this.readyState = 3;
  }

  /** The server accepts the connection. */
  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  /** The server sends a message (version 1 is added). */
  receive(message: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify({ version: 1, ...message }) });
  }

  /** The connection is lost. */
  drop(): void {
    this.readyState = 3;
    this.onclose?.({});
  }

  /** The messages sent of one type, such as "subscribe". */
  sentOfType(type: string): Record<string, unknown>[] {
    return this.sent.filter((message) => message.type === type);
  }

  clearSent(): void {
    this.sent = [];
  }
}
