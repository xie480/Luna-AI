/**
 * Snowflake ID Generator
 * 
 * Generates 64-bit unique IDs based on Twitter's Snowflake algorithm.
 * The ID is composed of:
 * - 1 bit: Unused (always 0 to ensure positive numbers)
 * - 41 bits: Timestamp (milliseconds since epoch)
 * - 10 bits: Node ID (0-1023)
 * - 12 bits: Sequence number (0-4095)
 */

export class Snowflake {
  // Epoch is set to 2024-01-01 00:00:00 UTC
  private static readonly EPOCH = 1704067200000n;

  private static readonly NODE_BITS = 10n;
  private static readonly SEQUENCE_BITS = 12n;

  private static readonly MAX_NODE = -1n ^ (-1n << Snowflake.NODE_BITS);
  private static readonly MAX_SEQUENCE = -1n ^ (-1n << Snowflake.SEQUENCE_BITS);

  private static readonly NODE_SHIFT = Snowflake.SEQUENCE_BITS;
  private static readonly TIMESTAMP_SHIFT = Snowflake.SEQUENCE_BITS + Snowflake.NODE_BITS;

  private nodeId: bigint;
  private sequence: bigint = 0n;
  private lastTimestamp: bigint = -1n;

  /**
   * Creates a new Snowflake generator
   * @param nodeId Node ID (0-1023)
   */
  constructor(nodeId: number | bigint) {
    const id = BigInt(nodeId);
    if (id < 0n || id > Snowflake.MAX_NODE) {
      throw new Error(`Node ID must be between 0 and ${Snowflake.MAX_NODE}`);
    }
    this.nodeId = id;
  }

  /**
   * Generates a new unique ID
   * @returns A 64-bit integer as a string to prevent precision loss in JS
   */
  public generate(): string {
    let timestamp = this.getCurrentTimestamp();

    if (timestamp < this.lastTimestamp) {
      throw new Error('Clock moved backwards. Refusing to generate id');
    }

    if (timestamp === this.lastTimestamp) {
      this.sequence = (this.sequence + 1n) & Snowflake.MAX_SEQUENCE;
      if (this.sequence === 0n) {
        // Sequence overflow, wait for next millisecond
        timestamp = this.waitNextMillis(this.lastTimestamp);
      }
    } else {
      this.sequence = 0n;
    }

    this.lastTimestamp = timestamp;

    const id =
      ((timestamp - Snowflake.EPOCH) << Snowflake.TIMESTAMP_SHIFT) |
      (this.nodeId << Snowflake.NODE_SHIFT) |
      this.sequence;

    return id.toString();
  }

  private getCurrentTimestamp(): bigint {
    return BigInt(Date.now());
  }

  private waitNextMillis(lastTimestamp: bigint): bigint {
    let timestamp = this.getCurrentTimestamp();
    while (timestamp <= lastTimestamp) {
      timestamp = this.getCurrentTimestamp();
    }
    return timestamp;
  }
}

// Global instance for convenience
let globalNode: Snowflake | null = null;

/**
 * Initializes the global snowflake node
 * @param nodeId Node ID (0-1023)
 */
export function initGlobalNode(nodeId: number): void {
  if (!globalNode) {
    globalNode = new Snowflake(nodeId);
  }
}

/**
 * Generates an ID using the global node
 * @returns A unique ID as a string
 */
export function generateId(): string {
  if (!globalNode) {
    // Fallback to node 1 if not initialized
    initGlobalNode(1);
  }
  return globalNode!.generate();
}
