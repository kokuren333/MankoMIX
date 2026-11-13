// mankomix_dsp.cpp -- C ABI of the MankoMIX native DSP core.
//
// SPDX-License-Identifier: Apache-2.0
//
// This layer owns parameter bookkeeping (lookup by stable id, clamping,
// storage) and argument validation. It never allocates inside mmx_process().
#include "mankomix_dsp.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <new>
#include <string>

#include "mmx_processor.h"

#define MMX_VERSION_STRING "0.2.0"

struct mmx_instance {
    const mmx::ProcessorSpec* spec;
    mmx::Processor* proc;
    int channels;
    double params[mmx::kMaxParams];
};

namespace {

const mmx::ProcessorSpec* find_spec(const char* id) {
    if (id == nullptr) return nullptr;
    int count = 0;
    const mmx::ProcessorSpec* const* reg = mmx::registry(&count);
    for (int i = 0; i < count; ++i) {
        if (std::strcmp(reg[i]->id, id) == 0) return reg[i];
    }
    return nullptr;
}

int find_param(const mmx::ProcessorSpec* spec, const char* id) {
    if (id == nullptr) return -1;
    for (int i = 0; i < spec->num_params; ++i) {
        if (std::strcmp(spec->params[i].id, id) == 0) return i;
    }
    return -1;
}

void append_escaped(std::string& out, const char* s) {
    out.push_back('"');
    for (const char* p = s; *p != '\0'; ++p) {
        const unsigned char ch = static_cast<unsigned char>(*p);
        switch (ch) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\t': out += "\\t"; break;
            default:
                if (ch < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", ch);
                    out += buf;
                } else {
                    out.push_back(static_cast<char>(ch));
                }
        }
    }
    out.push_back('"');
}

void append_number(std::string& out, double v) {
    char buf[40];
    std::snprintf(buf, sizeof(buf), "%.17g", v);
    for (char* p = buf; *p != '\0'; ++p) {
        if (*p == ',') *p = '.';  // guard against a non-C numeric locale
    }
    out += buf;
}

void append_kv(std::string& out, const char* key, const char* value, bool comma = true) {
    append_escaped(out, key);
    out.push_back(':');
    append_escaped(out, value);
    if (comma) out.push_back(',');
}

std::string spec_json(const mmx::ProcessorSpec* spec) {
    std::string j;
    j.reserve(1024);
    j += '{';
    append_kv(j, "id", spec->id);
    append_kv(j, "type", spec->type);
    append_kv(j, "role", spec->role);
    append_kv(j, "name", spec->name);
    append_kv(j, "summary", spec->summary);
    j += "\"origin\":{";
    append_kv(j, "source", spec->origin.source);
    append_kv(j, "plugin", spec->origin.plugin);
    append_kv(j, "license", spec->origin.license);
    append_kv(j, "files", spec->origin.files);
    if (std::strcmp(spec->origin.source, "airwindows") == 0) {
        append_kv(j, "repository", "https://github.com/airwindows/airwindows");
        append_kv(j, "commit", mmx::kAirwindowsCommit, false);
    } else {
        j.pop_back();
    }
    j += "},\"channels\":{\"min\":1,\"max\":";
    append_number(j, mmx::kMaxChannels);
    j += "},\"sample_format\":\"planar_f64_inplace\",\"params\":[";
    for (int i = 0; i < spec->num_params; ++i) {
        const mmx::ParamSpec& p = spec->params[i];
        if (i > 0) j += ',';
        j += '{';
        append_kv(j, "id", p.id);
        append_kv(j, "unit", p.unit);
        j += "\"min\":";
        append_number(j, p.min_value);
        j += ",\"max\":";
        append_number(j, p.max_value);
        j += ",\"default\":";
        append_number(j, p.default_value);
        j += ',';
        append_kv(j, "description", p.description, false);
        j += '}';
    }
    j += "],\"realtime\":{\"block_ok\":";
    j += spec->block_ok ? "true" : "false";
    j += ",\"latency_samples\":";
    append_number(j, spec->latency_samples);
    j += ",\"allocates_in_process\":false,\"deterministic\":true}}";
    return j;
}

std::string compiler_string() {
    char buf[96];
#if defined(__clang__)
    std::snprintf(buf, sizeof(buf), "clang %d.%d.%d", __clang_major__, __clang_minor__, __clang_patchlevel__);
#elif defined(_MSC_VER)
    std::snprintf(buf, sizeof(buf), "msvc %d", static_cast<int>(_MSC_FULL_VER));
#elif defined(__GNUC__)
    std::snprintf(buf, sizeof(buf), "gcc %d.%d.%d", __GNUC__, __GNUC_MINOR__, __GNUC_PATCHLEVEL__);
#else
    std::snprintf(buf, sizeof(buf), "unknown");
#endif
    return buf;
}

}  // namespace

extern "C" {

MMX_API const char* mmx_version(void) { return MMX_VERSION_STRING; }

MMX_API int mmx_abi_version(void) { return MMX_ABI_VERSION; }

MMX_API const char* mmx_build_info(void) {
    static const std::string info = [] {
        std::string j = "{";
        append_kv(j, "version", MMX_VERSION_STRING);
        j += "\"abi\":";
        append_number(j, MMX_ABI_VERSION);
        j += ',';
        append_kv(j, "compiler", compiler_string().c_str());
        append_kv(j, "precision", "double");
        append_kv(j, "layout", "planar_inplace");
        append_kv(j, "airwindows_commit", mmx::kAirwindowsCommit, false);
        j += '}';
        return j;
    }();
    return info.c_str();
}

MMX_API int mmx_processor_count(void) {
    int count = 0;
    mmx::registry(&count);
    return count;
}

MMX_API int mmx_processor_info(int index, char* buf, size_t buflen) {
    int count = 0;
    const mmx::ProcessorSpec* const* reg = mmx::registry(&count);
    if (index < 0 || index >= count) return MMX_ERR_BAD_ARGUMENT;
    const std::string j = spec_json(reg[index]);
    if (buf != nullptr && buflen > 0) {
        const size_t n = (j.size() < buflen - 1) ? j.size() : buflen - 1;
        std::memcpy(buf, j.data(), n);
        buf[n] = '\0';
    }
    return static_cast<int>(j.size());
}

MMX_API mmx_instance* mmx_create(const char* processor_id, double sample_rate, int channels) {
    const mmx::ProcessorSpec* spec = find_spec(processor_id);
    if (spec == nullptr) return nullptr;
    if (!(sample_rate >= 8000.0 && sample_rate <= 768000.0)) return nullptr;
    if (channels < 1 || channels > mmx::kMaxChannels) return nullptr;
    if (spec->num_params > mmx::kMaxParams) return nullptr;

    mmx_instance* inst = new (std::nothrow) mmx_instance();
    if (inst == nullptr) return nullptr;
    inst->spec = spec;
    inst->channels = channels;
    try {
        inst->proc = spec->create(sample_rate, channels);
    } catch (...) {  // no exception may cross the C ABI
        inst->proc = nullptr;
    }
    if (inst->proc == nullptr) {
        delete inst;
        return nullptr;
    }
    for (int i = 0; i < spec->num_params; ++i) {
        inst->params[i] = spec->params[i].default_value;
        inst->proc->set_param(i, inst->params[i]);
    }
    return inst;
}

MMX_API int mmx_set_param(mmx_instance* inst, const char* param_id, double value) {
    if (inst == nullptr || param_id == nullptr) return MMX_ERR_NULL;
    const int idx = find_param(inst->spec, param_id);
    if (idx < 0) return MMX_ERR_UNKNOWN_PARAM;
    if (!std::isfinite(value)) return MMX_ERR_BAD_VALUE;
    const mmx::ParamSpec& p = inst->spec->params[idx];
    int status = MMX_OK;
    if (value < p.min_value) {
        value = p.min_value;
        status = MMX_OK_CLAMPED;
    } else if (value > p.max_value) {
        value = p.max_value;
        status = MMX_OK_CLAMPED;
    }
    inst->params[idx] = value;
    inst->proc->set_param(idx, value);
    return status;
}

MMX_API int mmx_get_param(const mmx_instance* inst, const char* param_id, double* out_value) {
    if (inst == nullptr || param_id == nullptr || out_value == nullptr) return MMX_ERR_NULL;
    const int idx = find_param(inst->spec, param_id);
    if (idx < 0) return MMX_ERR_UNKNOWN_PARAM;
    *out_value = inst->params[idx];
    return MMX_OK;
}

MMX_API int mmx_latency(const mmx_instance* inst) {
    if (inst == nullptr) return MMX_ERR_NULL;
    return inst->proc->latency();
}

MMX_API int mmx_process(mmx_instance* inst, double* const* channels, int64_t frames) {
    if (inst == nullptr || channels == nullptr) return MMX_ERR_NULL;
    if (frames < 0) return MMX_ERR_BAD_ARGUMENT;
    if (frames == 0) return MMX_OK;
    for (int c = 0; c < inst->channels; ++c) {
        if (channels[c] == nullptr) return MMX_ERR_NULL;
    }
    inst->proc->process(channels, frames);
    return MMX_OK;
}

MMX_API int mmx_reset(mmx_instance* inst) {
    if (inst == nullptr) return MMX_ERR_NULL;
    inst->proc->reset();
    return MMX_OK;
}

MMX_API void mmx_destroy(mmx_instance* inst) {
    if (inst == nullptr) return;
    delete inst->proc;
    delete inst;
}

MMX_API int mmx_smooth_attack_release(double* buf, int64_t frames, double a_att, double ia_att,
                                      double a_rel, double ia_rel, double* state) {
    if (buf == nullptr || state == nullptr) return MMX_ERR_NULL;
    if (frames < 0) return MMX_ERR_BAD_ARGUMENT;
    double prev = *state;
    for (int64_t i = 0; i < frames; ++i) {
        const double g = buf[i];
        // Same operation order as the Python reference loop (two products, one sum).
        if (g > prev) {
            prev = a_att * prev + ia_att * g;
        } else {
            prev = a_rel * prev + ia_rel * g;
        }
        buf[i] = prev;
    }
    *state = prev;
    return MMX_OK;
}

}  // extern "C"
