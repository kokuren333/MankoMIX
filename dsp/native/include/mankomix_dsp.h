/*
 * mankomix_dsp.h -- C ABI of the MankoMIX native DSP core.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Contract (docs/SPEC.md sections 3.2, 6.5.2, 14.2):
 *   - The core depends on no UI, file IO, network, agent layer or plugin SDK.
 *     Inputs are sample buffers and parameters only.
 *   - Every processor has a stable processor id and stable parameter ids
 *     (never renamed across versions; new ids may be added).
 *   - mmx_process() never allocates, never locks and never performs IO.
 *     All memory is acquired in mmx_create().
 *   - Processing is deterministic: identical input, parameters and call
 *     sequence give bit-identical output, independent of how the signal is
 *     split into blocks.
 *
 * Sample format: PLANAR double precision, processed IN PLACE.
 *   `channels` is an array of `num_channels` pointers; channel c holds
 *   `frames` contiguous doubles. Nominal full scale is +/-1.0.
 *
 * Versioning: MMX_ABI_VERSION is bumped on any incompatible change of this
 * header (function signatures, semantics, JSON keys being removed). Callers
 * should compare mmx_abi_version() with the value they were written for.
 */
#ifndef MANKOMIX_DSP_H
#define MANKOMIX_DSP_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  if defined(MMX_BUILDING_LIBRARY)
#    define MMX_API __declspec(dllexport)
#  else
#    define MMX_API __declspec(dllimport)
#  endif
#else
#  define MMX_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define MMX_ABI_VERSION 1

/* Maximum channel count a processor instance accepts. */
#define MMX_MAX_CHANNELS 8

/* Status codes. Non-negative means success. */
#define MMX_OK 0
#define MMX_OK_CLAMPED 1          /* parameter value was clamped into range */
#define MMX_ERR_NULL (-1)         /* null handle or pointer */
#define MMX_ERR_UNKNOWN_PARAM (-2)
#define MMX_ERR_BAD_VALUE (-3)    /* NaN or infinite parameter value */
#define MMX_ERR_BAD_ARGUMENT (-4) /* e.g. negative frame count */

typedef struct mmx_instance mmx_instance;

/* Library version string, "MAJOR.MINOR.PATCH". Static storage. */
MMX_API const char* mmx_version(void);

/* ABI version (MMX_ABI_VERSION of the built library). */
MMX_API int mmx_abi_version(void);

/*
 * Build information as a JSON object (static storage), e.g.
 * {"version":"0.2.0","abi":1,"compiler":"...","precision":"double",
 *  "layout":"planar","airwindows_commit":"..."}.
 */
MMX_API const char* mmx_build_info(void);

/* Number of processors compiled into the library. */
MMX_API int mmx_processor_count(void);

/*
 * Writes the JSON description of processor `index` into `buf` (NUL
 * terminated, truncated to `buflen`). Returns the full JSON length in bytes
 * excluding the terminator (snprintf semantics: call with buf == NULL,
 * buflen == 0 to query the size), or a negative status on a bad index.
 *
 * JSON shape:
 * {"id": "aw.purest_drive", "type": "saturator", "name": "...",
 *  "origin": {...}, "channels": {"min": 1, "max": 8},
 *  "params": [{"id", "unit", "min", "max", "default", "description"}],
 *  "realtime": {"block_ok": true, "latency_samples": 0,
 *               "allocates_in_process": false}}
 */
MMX_API int mmx_processor_info(int index, char* buf, size_t buflen);

/*
 * Creates an instance of processor `processor_id` (the "id" field of the
 * JSON) at `sample_rate` Hz (8000..768000) with `channels` channels
 * (1..MMX_MAX_CHANNELS). Parameters start at their defaults.
 * Returns NULL on an unknown id or an invalid argument.
 */
MMX_API mmx_instance* mmx_create(const char* processor_id, double sample_rate, int channels);

/* Sets a parameter by its stable id. Out-of-range values are clamped. */
MMX_API int mmx_set_param(mmx_instance* inst, const char* param_id, double value);

/* Reads the current value of a parameter. Returns a status code. */
MMX_API int mmx_get_param(const mmx_instance* inst, const char* param_id, double* out_value);

/* Processing latency of this instance in samples. */
MMX_API int mmx_latency(const mmx_instance* inst);

/*
 * Processes `frames` frames in place. `channels` holds exactly the channel
 * count given to mmx_create(). Realtime safe: no allocation, no IO.
 */
MMX_API int mmx_process(mmx_instance* inst, double* const* channels, int64_t frames);

/* Clears the signal state (as if newly created); parameters are kept. */
MMX_API int mmx_reset(mmx_instance* inst);

/* Destroys an instance. Null is accepted. */
MMX_API void mmx_destroy(mmx_instance* inst);

/*
 * Utility kernel (added in library 0.2.0, ABI 1 compatible): decoupled
 * attack/release one-pole smoother used by the gain computers of the
 * dynamics processors (compressor, dynamic EQ, de-esser). In place on one
 * contiguous buffer of `frames` doubles:
 *
 *   y = (x[n] > y) ? a_att * y + ia_att * x[n] : a_rel * y + ia_rel * x[n]
 *
 * `*state` holds y before the first sample and receives y after the last.
 * The coefficients are passed in full (ia = 1 - a computed by the caller) so
 * that a caller-side reference loop with the same operation order is
 * bit-identical (no FMA contraction, see CMakeLists.txt). No allocation.
 */
MMX_API int mmx_smooth_attack_release(double* buf, int64_t frames, double a_att, double ia_att,
                                      double a_rel, double ia_rel, double* state);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* MANKOMIX_DSP_H */
