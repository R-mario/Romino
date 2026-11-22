#!/usr/bin/env python3
"""Parche quirúrgico para bark.cpp:
1. Ventana dinámica en Fine GPT (evita rellenar a 1024 frames en clips cortos -> 9x más rápido).
2. Tope adaptativo de n_steps_text_encoder según longitud real del prompt (evita bucles de
   alucinación de 768 tokens / 15 s que provocaban timeouts de 180 s en frases largas o cortas).
"""

from __future__ import annotations

import sys
from pathlib import Path

OLD_SEMANTIC_STEPS = "    int32_t n_steps_text_encoder = params.n_steps_text_encoder;"
NEW_SEMANTIC_STEPS = """    // adaptive semantic cap to avoid 768-step hallucination/timeout loops on CPU
    int real_text_tokens = 0;
    for (int k = 0; k < 256 && k < (int)input.size(); k++) {
        if (input[k] != params.text_pad_token) {
            real_text_tokens++;
        }
    }
    int32_t n_steps_text_encoder = std::min(
        params.n_steps_text_encoder,
        std::max(140, real_text_tokens * 22 + 80));"""

OLD_INTERNAL = (
    "    ggml_backend_tensor_get(inpL, logits.data(), 0, sizeof(float) * n_vocab * block_size);"
)
NEW_INTERNAL = (
    "    ggml_backend_tensor_get(inpL, logits.data(), 0, sizeof(float) * n_vocab * N);"
)

OLD_FINE_BLOCK = """    // spatial padding if sequence is too short
    if (original_seq_len < 1024) {
        n_remove_from_end = 1024 - original_seq_len;
        for (int i = original_seq_len; i < 1024; i++) {
            bark_sequence _tmp(n_fine_codebooks, codebook_size);
            input.push_back(_tmp);
        }
    }

    int n_loops = std::max(0, (int)ceilf((input.size() - 1024) / 512.f)) + 1;

    bark_codes in_arr = input;  // [seq_length, n_codes]

    for (int n = 0; n < n_loops; n++) {
        int start_idx = std::min(n * 512, (int)in_arr.size() - 1024);
        int start_fill_idx = std::min(n * 512, (int)in_arr.size() - 512);
        int rel_start_fill_idx = start_fill_idx - start_idx;

        // in_buffer: [n_codes*seq_length] (sequences are contiguous)
        bark_sequence in_buffer;
        for (int i = 0; i < n_fine_codebooks; i++) {
            for (int j = start_idx; j < start_idx + 1024; j++) {
                in_buffer.push_back(in_arr[j][i]);
            }
        }

        for (int nn = n_coarse; nn < n_fine_codebooks; nn++) {
            if (params.progress_callback) {
                const int progress_cur = 100*(n*(n_fine_codebooks-n_coarse)+(nn-n_coarse+1))/(n_loops*(n_fine_codebooks-n_coarse));

                params.progress_callback(
                    bctx, bark_encoding_step::FINE, progress_cur, params.progress_callback_user_data);
            }

            if (!bark_eval_fine_encoder_internal(bctx, in_buffer, logits, nn, n_threads)) {
                fprintf(stderr, "%s: Could not generate token\\n", __func__);
                return false;
            }
            for (int i = 0; i < 1024; i++) {
                std::vector<float> relevant_logits(
                    logits.begin() + i * 1056,
                    logits.begin() + (i + 1) * 1056);
                relevant_logits.resize(codebook_size);

                bark_token next = gpt_sample(
                    relevant_logits, bctx->rng, temp, NULL, &model.t_sample_us,
                    &model.n_sample);

                in_buffer[nn * 1024 + rel_start_fill_idx + i] = next;
            }
        }

        // transfer over info into model_in
        for (int nn = n_coarse; nn < n_fine_codebooks; nn++) {
            for (int j = 0; j < codebook_size - rel_start_fill_idx; j++) {
                in_arr[start_fill_idx + j][nn] = in_buffer[nn * 1024 + rel_start_fill_idx + j];
            }
        }
    }"""

NEW_FINE_BLOCK = """    // dynamic window padding for short clips (avoids wasted 1024-token attention on mobile CPU)
    const int win_len = (original_seq_len < 1024)
        ? std::min(1024, std::max(32, ((original_seq_len + 31) / 32) * 32))
        : 1024;

    if (original_seq_len < win_len) {
        n_remove_from_end = win_len - original_seq_len;
        for (int i = original_seq_len; i < win_len; i++) {
            bark_sequence _tmp(n_fine_codebooks, codebook_size);
            input.push_back(_tmp);
        }
    }

    int n_loops = (original_seq_len < 1024)
        ? 1
        : (std::max(0, (int)ceilf((input.size() - 1024) / 512.f)) + 1);

    bark_codes in_arr = input;  // [seq_length, n_codes]

    for (int n = 0; n < n_loops; n++) {
        int start_idx = (original_seq_len < 1024) ? 0 : std::min(n * 512, (int)in_arr.size() - 1024);
        int start_fill_idx = (original_seq_len < 1024) ? 0 : std::min(n * 512, (int)in_arr.size() - 512);
        int rel_start_fill_idx = start_fill_idx - start_idx;

        // in_buffer: [n_codes*win_len] (sequences are contiguous)
        bark_sequence in_buffer;
        in_buffer.reserve(n_fine_codebooks * win_len);
        for (int i = 0; i < n_fine_codebooks; i++) {
            for (int j = start_idx; j < start_idx + win_len; j++) {
                in_buffer.push_back(in_arr[j][i]);
            }
        }

        for (int nn = n_coarse; nn < n_fine_codebooks; nn++) {
            if (params.progress_callback) {
                const int progress_cur = 100*(n*(n_fine_codebooks-n_coarse)+(nn-n_coarse+1))/(n_loops*(n_fine_codebooks-n_coarse));

                params.progress_callback(
                    bctx, bark_encoding_step::FINE, progress_cur, params.progress_callback_user_data);
            }

            if (!bark_eval_fine_encoder_internal(bctx, in_buffer, logits, nn, n_threads)) {
                fprintf(stderr, "%s: Could not generate token\\n", __func__);
                return false;
            }
            for (int i = 0; i < win_len - rel_start_fill_idx; i++) {
                const int pos = rel_start_fill_idx + i;
                std::vector<float> relevant_logits(
                    logits.begin() + pos * 1056,
                    logits.begin() + (pos + 1) * 1056);
                relevant_logits.resize(codebook_size);

                bark_token next = gpt_sample(
                    relevant_logits, bctx->rng, temp, NULL, &model.t_sample_us,
                    &model.n_sample);

                in_buffer[nn * win_len + pos] = next;
            }
        }

        // transfer over info into model_in
        for (int nn = n_coarse; nn < n_fine_codebooks; nn++) {
            for (int j = 0; j < win_len - rel_start_fill_idx; j++) {
                in_arr[start_fill_idx + j][nn] = in_buffer[nn * win_len + rel_start_fill_idx + j];
            }
        }
    }"""


def patch_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    updated = text
    changed = False

    if "dynamic window padding for short clips" not in updated:
        if OLD_INTERNAL not in updated or OLD_FINE_BLOCK not in updated:
            print(f"[ERR] No se encontraron bloques Fine GPT en {path}", file=sys.stderr)
            return 1
        updated = updated.replace(OLD_INTERNAL, NEW_INTERNAL, 1).replace(
            OLD_FINE_BLOCK, NEW_FINE_BLOCK, 1
        )
        changed = True

    if "adaptive semantic cap to avoid 768-step" not in updated:
        if OLD_SEMANTIC_STEPS not in updated:
            print(f"[ERR] No se encontró OLD_SEMANTIC_STEPS en {path}", file=sys.stderr)
            return 1
        updated = updated.replace(OLD_SEMANTIC_STEPS, NEW_SEMANTIC_STEPS, 1)
        changed = True

    if changed:
        path.write_text(updated, encoding="utf-8")
        print(f"[PATCHED] Parches Fine dinámico + tope semántico adaptativo aplicados en {path}")
    else:
        print(f"[OK] Todos los parches ya estaban aplicados en {path}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "bark.cpp" / "bark.cpp"
    sys.exit(patch_file(target))
