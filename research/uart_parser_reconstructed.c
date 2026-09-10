/*
 * Reconstruction of the UART frame parser from the Zoom75 TIGA display module
 * firmware (FreqChip FR8008HP, bank A, image dumped 10.09.2026).
 *
 * Function entry:  0x10021706
 * Jump table:      0x10021722  (tbb, 6 entries: 03 09 0c 10 1b 2b)
 * Dispatch:        0x10020E26  (error / delivery callback)
 * msg_id 0x32:     0x10021228  (special handler)
 *
 * THIS IS A RECONSTRUCTION, NOT RECOVERED SOURCE. Field offsets, constants and
 * control flow come straight from the disassembly and are accurate; names and
 * types are invented.
 *
 * Confidence:
 *   high   — state machine shape, 0xA5 sync, big-endian length, checksum formula,
 *            0x43 length cap, 0xFF checksum wildcard, msg_id 0x32 special case
 *   medium — the meaning of the error code 0xFD and of the ready flag
 *   low    — names of everything
 */

#include <stdint.h>

/* ------------------------------------------------------------------ constants */

#define FRAME_SYNC        0xA5    /* start byte, matched at 0x10021728          */
#define MAX_PAYLOAD       0x43    /* 67 — length cap at 0x1002174A              */
#define RX_BUFFER_SIZE    0x44    /* 68 — index cap at 0x1002176E               */
#define CHECKSUM_WILDCARD 0xFF    /* accepted unconditionally at 0x100217A0     */
#define ERR_BAD_CHECKSUM  0xFD    /* passed to the callback at 0x100217A4       */
#define MSGID_SPECIAL     0x32    /* extra handler at 0x100217B2                */

enum rx_state {
    ST_SYNC    = 0,   /* waiting for 0xA5                     */
    ST_MSGID   = 1,   /* next byte is the message id          */
    ST_LEN_HI  = 2,   /* next byte is the high length byte    */
    ST_LEN_LO  = 3,   /* next byte is the low length byte     */
    ST_PAYLOAD = 4,   /* collecting payload bytes             */
    ST_CHECK   = 5    /* next byte is the checksum            */
};

/* ------------------------------------------------------------------ structures */

/*
 * Parser state. Two separate objects in the original, loaded from two literals
 * at 0x1002170A and 0x1002170C.
 */
typedef struct {
    uint8_t state;        /* +0  enum rx_state                                 */
    uint8_t frame_ready;  /* +1  set at 0x100217AE once the checksum matches   */
} rx_fsm_t;

typedef struct {
    uint8_t  msg_id;              /* +0  stored at 0x10021734                  */
    uint8_t  pad;                 /* +1                                        */
    uint16_t length;              /* +2  big-endian on the wire                */
    uint16_t index;               /* +4  payload write cursor                  */
    uint8_t  payload[RX_BUFFER_SIZE];  /* +6                                   */
} rx_frame_t;

extern rx_fsm_t   g_fsm;
extern rx_frame_t g_frame;

/* Called on a bad frame, and elsewhere as the general delivery path.
   Signature inferred from the call at 0x100217A8: (msg_id, code). */
extern void frame_report(uint8_t msg_id, uint8_t code);

/* Handler invoked only for msg_id 0x32 (0x10021228). */
extern void handle_msg_32(void);

/* ------------------------------------------------------------------ the parser */

/*
 * One byte in, one step of the state machine. Called from the UART RX path.
 *
 * Wire format, confirmed by this function:
 *
 *     A5 | msg_id | len_hi | len_lo | payload[len] | checksum
 *
 *   - length is BIG-endian  (0x10021742: len = (len_hi << 8) | len_lo)
 *   - checksum = ~(msg_id + len_hi + len_lo + sum(payload)) & 0xFF
 *     which is exactly the 0xFF - sum formula observed on the wire
 *   - a checksum byte of 0xFF is accepted without verification
 *   - frames longer than 0x43 payload bytes are dropped and the parser resyncs
 */
void uart_rx_byte(uint8_t b)
{
    switch (g_fsm.state) {

    /* --- 0x10021728: hunt for the sync byte --------------------------- */
    case ST_SYNC:
        if (b == FRAME_SYNC)
            g_fsm.state = ST_MSGID;
        break;

    /* --- 0x10021734 ---------------------------------------------------- */
    case ST_MSGID:
        g_frame.msg_id = b;
        g_fsm.state    = ST_LEN_HI;
        break;

    /* --- 0x1002173A ---------------------------------------------------- */
    case ST_LEN_HI:
        g_frame.length = b;              /* high byte parked here */
        g_fsm.state    = ST_LEN_LO;
        break;

    /* --- 0x10021742: assemble the big-endian length -------------------- */
    case ST_LEN_LO:
        g_frame.length = (uint16_t)((g_frame.length << 8) | b);
        if (g_frame.length > MAX_PAYLOAD) {
            g_fsm.state = ST_SYNC;       /* oversized, resync */
            break;
        }
        g_fsm.state = ST_PAYLOAD;
        break;

    /* --- 0x10021758: collect the payload ------------------------------- */
    case ST_PAYLOAD:
        g_frame.payload[g_frame.index++] = b;
        if (g_frame.index == g_frame.length ||
            g_frame.index >= RX_BUFFER_SIZE) {
            g_frame.index = 0;
            g_fsm.state   = ST_CHECK;
        }
        break;

    /* --- 0x10021778: verify and deliver -------------------------------- */
    case ST_CHECK: {
        uint8_t  msg_id = g_frame.msg_id;
        uint16_t len    = g_frame.length;

        /* 0x1002177A: seed with msg_id + len_lo + len_hi */
        uint8_t sum = (uint8_t)(msg_id + (uint8_t)len + (uint8_t)(len >> 8));

        /* 0x10021784: add every payload byte */
        for (uint16_t i = 0; i < len; i++)
            sum = (uint8_t)(sum + g_frame.payload[i]);

        uint8_t expected = (uint8_t)~sum;      /* 0x10021798: mvns */

        if (expected != b && b != CHECKSUM_WILDCARD) {
            /* 0x100217A4: reject */
            frame_report(msg_id, ERR_BAD_CHECKSUM);
        } else {
            /* 0x100217AE: accept */
            g_fsm.frame_ready = 1;

            /* 0x100217B2: one message id gets extra treatment */
            if (msg_id == MSGID_SPECIAL)
                handle_msg_32();
        }

        g_fsm.state   = ST_SYNC;
        g_frame.index = 0;
        break;
    }

    default:
        g_fsm.state = ST_SYNC;
        break;
    }
}
