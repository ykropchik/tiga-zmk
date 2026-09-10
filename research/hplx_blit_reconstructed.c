/*
 * Reconstruction of the HPLX span blitter from the Zoom75 TIGA display module
 * firmware (FreqChip FR8008HP, bank A, image dumped 10.09.2026).
 *
 * Function entry:  0x1000A03C
 * Analysed range:  0x1000A03C .. 0x1000A2C8
 *
 * THIS IS A RECONSTRUCTION, NOT RECOVERED SOURCE.
 * Symbol names, types and struct layouts were destroyed by the compiler and have
 * been invented here to make the logic readable. Field offsets, constants and
 * control flow are taken directly from the disassembly and are accurate;
 * everything else is interpretation and may be wrong.
 *
 * Confidence:
 *   high   — container header checks, span walk, +8 header skip, 0x140 bound
 *   medium — clip-rectangle arithmetic, meaning of the RLE/literal flag
 *   low    — the blend call and the byte-triple stride, names of everything
 */

#include <stdint.h>
#include <string.h>

/* ------------------------------------------------------------------ constants */

#define HPLX_MAGIC        0x584C5048u   /* "HPLX", literal at 0x1000A2C8       */
#define SCREEN_W          0x140         /* 320 — hard bound checked at 0x1000A068 */
#define ROW_STRIDE_BYTES  0x280         /* 640 — divisor at 0x1000A14A         */
#define SPAN_HDR_BYTES    8             /* x_start + byte_len, skipped at 0x1000A21C */
#define SPAN_LIMIT        0x7D0         /* 2000 — runaway guard at 0x1000A1B0  */
#define TILE_ROWS         0xAC          /* 172 — added to base at 0x1000A086   */

/* ------------------------------------------------------------------ structures */

/*
 * The container as the firmware sees it. Offsets are from the disassembly:
 *   [0x00] magic          compared against HPLX_MAGIC at 0x1000A04E
 *   [0x08] width          loaded at 0x1000A056, bounded by 0x140
 *   [0x0C] height         loaded at 0x1000A060
 *   [0x28] row table      base added at 0x1000A180, entries are 8 bytes
 * The row table is indexed with `<< 3` (0x1000A17C, 0x1000A188), which matches
 * the (row_offset, row_size) pair layout established from the flash dumps.
 */
typedef struct {
    uint32_t magic;          /* 0x00 */
    uint32_t reserved04;     /* 0x04 */
    uint32_t width;          /* 0x08 */
    uint32_t height;         /* 0x0C */
    uint32_t pad[6];         /* 0x10 */
    uint32_t table_offset;   /* 0x28 */
    uint32_t data_offset;    /* 0x2C — loaded into sl at 0x1000A192 */
} hplx_header_t;

typedef struct {
    uint32_t offset;         /* relative to data_offset */
    uint32_t length;         /* bytes, including span headers */
} hplx_row_t;

typedef struct {
    uint32_t x_start;        /* pixels */
    uint32_t byte_len;       /* bytes of RGB565 that follow */
    /* uint16_t pixels[byte_len / 2]; */
} hplx_span_t;

/* Framebuffer / window descriptor referenced through a global at 0x1000A078.
   Byte at +2 gates an override of width; halfword at +0xC supplies it. */
typedef struct {
    uint8_t  unknown0;
    uint8_t  unknown1;
    uint8_t  width_override_enabled;   /* +2 */
    uint8_t  unknown3;
    uint16_t clip_y0;                  /* +4  compared at 0x1000A156 */
    uint16_t clip_y1;                  /* +6  compared at 0x1000A15C */
    uint16_t offset_x;                 /* +8  added at 0x1000A09A    */
    uint16_t offset_y;                 /* +0x0A                       */
    uint16_t width_override;           /* +0x0C                       */
} draw_ctx_t;

extern draw_ctx_t   g_ctx;
extern uint8_t     *g_framebuffer;     /* [+0x10] of the object at 0x1000A264 */
extern uint8_t      g_clip_enabled;    /* byte tested at 0x1000A146           */
extern uint8_t      g_offset_enabled;  /* byte tested at 0x1000A08C           */

/* Blend of two RGB565 pixels with a 5-bit alpha. Called at 0x100185B0.
   The alpha comes from a third byte shifted right by 3 (0x1000A23E), so the
   source is 3 bytes per pixel: 2 colour + 1 alpha. */
extern uint16_t pixel_blend(uint16_t dst, uint16_t src, uint8_t alpha5);

/* ------------------------------------------------------------------ the blitter */

/*
 * Original signature, inferred from register usage at entry:
 *   r0  = y0        vertical position of the destination window
 *   r1  = x0        horizontal position
 *   r2  = origin_x  base column, used for both clipping and the copy offset
 *   r3  = tile_base kept in r8, and TILE_ROWS (0xAC) is added to it
 *   [sp+0x690] = const hplx_header_t *img   (fifth argument, on the stack)
 */
int hplx_blit(uint16_t y0, uint16_t x0, uint16_t origin_x,
              uint16_t tile_base, const hplx_header_t *img)
{
    uint8_t  scratch[0x3C0];      /* sp+0x000 .. staging area for span data   */
    uint8_t  linebuf[0x280];      /* sp+0x3C0 .. one composed row, 320 px     */

    uint32_t width, height;
    uint32_t clip_left, clip_right;
    uint32_t row_index;

    /* --- 0x1000A04A: reject anything that is not an HPLX container -------- */
    if (img->magic != HPLX_MAGIC)
        return 0;

    width  = img->width;
    height = img->height;

    /* --- 0x1000A068: refuse images wider than the panel ------------------- */
    if ((uint16_t)width > SCREEN_W)
        return 0;

    /* --- 0x1000A07A: an active context may override the width ------------- */
    if (g_ctx.width_override_enabled)
        width = g_ctx.width_override;

    /* --- 0x1000A086: the destination spans TILE_ROWS rows ----------------- */
    uint32_t tile_end = tile_base + TILE_ROWS;

    /* --- 0x1000A092: optional global drawing offset ----------------------- */
    if (g_offset_enabled) {
        clip_left  = origin_x + g_ctx.offset_x;
        clip_right = origin_x + g_ctx.offset_y;
    } else {
        clip_left  = origin_x;
        clip_right = origin_x + SCREEN_W;
    }

    /* --- 0x1000A0AA .. 0x1000A0CE: reject fully clipped placements -------- */
    if (x0 >= (uint16_t)tile_end)          return 0;
    if (x0 + height < tile_base)           return 0;
    if (y0 >= (uint16_t)clip_right)        return 0;
    if (y0 + width  < clip_left)           return 0;

    /* --- 0x1000A0D0 .. 0x1000A114: clamp to the visible rectangle --------- */
    uint32_t skip_rows = (x0 < tile_base) ? (tile_base - x0) : 0;
    uint32_t skip_cols = (y0 < clip_left) ? (clip_left - y0) : 0;

    uint32_t visible_rows = (x0 + height > tile_end)
                          ? (tile_end - (x0 + skip_rows))
                          : (height - skip_rows);

    uint32_t visible_cols = (y0 + width > clip_right)
                          ? (clip_right - (y0 + skip_cols))
                          : (width - skip_cols);

    /*
     * 0x1000A11E: destination byte offset.
     *   ((x0 + skip_rows - tile_base) * 5) << 6 == * 320   rows
     *   plus (y0 - origin_x)                               columns
     *   the whole thing << 1                               2 bytes per pixel
     */
    uint32_t dst_base = ((y0 - origin_x)
                      + (((x0 + skip_rows - tile_base) * 5) << 6)) * 2;

    /* --- 0x1000A29A: iterate the visible rows ----------------------------- */
    for (row_index = 0; row_index < visible_rows; row_index++) {

        uint32_t dst_off = dst_base + ((row_index * 5) << 7);   /* * 640 */

        /* --- 0x1000A146: optional vertical clip against the context ------ */
        if (g_clip_enabled) {
            uint32_t scanline = dst_off / ROW_STRIDE_BYTES;
            if (scanline < g_ctx.clip_y0 || scanline >= g_ctx.clip_y1)
                continue;                                /* 0x1000A258 */
        }

        /* --- 0x1000A16C: locate this row in the table -------------------- */
        const hplx_row_t *row =
            (const hplx_row_t *)((const uint8_t *)img
                                 + img->table_offset
                                 + (skip_rows + row_index) * sizeof(hplx_row_t));

        const uint8_t *span_ptr = (const uint8_t *)img + row->offset + 0x28;
        int32_t        remaining = (int32_t)row->length;
        uint32_t        guard    = 0;

        /* --- 0x1000A19A: walk the spans of this row ---------------------- */
        while (remaining > 0) {

            /* 0x1000A1B0: refuse to loop forever on corrupt data */
            if (++guard > SPAN_LIMIT)
                break;

            uint32_t x_start  = ((const uint32_t *)span_ptr)[0];
            int32_t  byte_len = ((const uint32_t *)span_ptr)[1];

            /*
             * 0x1000A1BE: the sign bit of byte_len selects the encoding.
             *   clear -> literal run,  count = byte_len / 3
             *   set   -> the low 16 bits hold the count directly
             * The /3 is consistent with 3 bytes per source pixel
             * (RGB565 + alpha), matching the blend path below.
             */
            uint32_t count;
            int      is_literal;

            if (byte_len >= 0) {
                count      = (uint32_t)byte_len / 3;
                is_literal = 1;
            } else {
                count      = (uint32_t)((byte_len >> 1) & 0xFFFF);
                is_literal = 0;
            }

            /* --- clip the span horizontally --------------------------- */
            uint32_t span_x   = x_start;
            uint32_t span_len = count;

            if (span_x + span_len <= skip_cols ||
                span_x >= skip_cols + visible_cols) {
                span_ptr  += SPAN_HDR_BYTES + (is_literal ? byte_len : 0);
                remaining -= SPAN_HDR_BYTES + (is_literal ? byte_len : 0);
                continue;                               /* 0x1000A278 */
            }
            if (span_x < skip_cols) {
                span_len -= (skip_cols - span_x);
                span_x    = skip_cols;
            }
            if (span_x + span_len > skip_cols + visible_cols)
                span_len = skip_cols + visible_cols - span_x;

            if (is_literal) {
                /*
                 * 0x1000A202 .. 0x1000A21E: straight copy of the span body
                 * into the staging buffer, skipping the 8-byte span header.
                 */
                memcpy(scratch,
                       span_ptr + SPAN_HDR_BYTES + (span_x - x_start) * 3,
                       span_len * 3);
            } else {
                /*
                 * 0x1000A224 .. 0x1000A25C: composite pixel by pixel.
                 * Source is 3 bytes: RGB565 little-endian plus a 5-bit alpha
                 * carried in the top bits of the third byte.
                 */
                for (uint32_t i = 0; i < span_len; i++) {
                    const uint8_t *src = span_ptr + SPAN_HDR_BYTES + i * 3;
                    uint16_t dst_px = *(const uint16_t *)(g_framebuffer
                                                          + dst_off + (span_x + i) * 2);
                    uint16_t src_px = (uint16_t)(src[0] | (src[1] << 8));
                    uint8_t  alpha5 = (uint8_t)(src[2] >> 3);

                    uint16_t out = pixel_blend(dst_px, src_px, alpha5);
                    linebuf[i * 2]     = (uint8_t)out;
                    linebuf[i * 2 + 1] = (uint8_t)(out >> 8);
                }
            }

            /* --- 0x1000A264 / 0x1000A2B0: flush into the framebuffer --- */
            memcpy(g_framebuffer + dst_off + span_x * 2,
                   is_literal ? (const void *)scratch : (const void *)linebuf,
                   span_len * 2);

            uint32_t consumed = SPAN_HDR_BYTES + (is_literal ? byte_len : 0);
            span_ptr  += consumed;
            remaining -= consumed;
        }
    }

    return 1;
}
