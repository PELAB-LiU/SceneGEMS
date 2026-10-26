import { liveChannelUrl } from "./clusterStore";
import { LiveChannel, type LiveChannelOptions } from "./liveChannel";

/**
 * One live channel per cluster, created on first use. A channel holds its socket only while
 * it has subscriptions, so the channels of clusters that are no longer selected go quiet
 * once their views unsubscribe.
 */

const channels = new Map<string, LiveChannel>();
let channelOptions: LiveChannelOptions = {};

/** The live channel of a cluster, by its operator URL. */
export function getLiveChannel(operatorUrl: string): LiveChannel {
  const url = liveChannelUrl(operatorUrl);
  let channel = channels.get(url);
  if (!channel) {
    channel = new LiveChannel(url, channelOptions);
    channels.set(url, channel);
  }
  return channel;
}

/** Closes every channel and sets the options of the ones created next (tests). */
export function resetLiveChannels(options: LiveChannelOptions = {}): void {
  for (const channel of channels.values()) {
    channel.close();
  }
  channels.clear();
  channelOptions = options;
}
