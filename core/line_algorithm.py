import numpy as np
import cv2
from numba import jit


# ==============================================================================
# 🟢 1. Numba 加速内核 (保持一致性)
# ==============================================================================
@jit(nopython=True, nogil=True, cache=True)
def _numba_calc_neighbor_diff_robust(signal_arr, edge_gain, use_robust):
    n = len(signal_arr)
    diff_arr = np.zeros(n, dtype=np.float32)
    offsets = np.array([-8, -6, -4, -2, 2, 4, 6, 8])

    for i in range(n):
        valid_row_sum = 0.0
        count = 0
        min_v = 1e10;
        max_v = -1.0

        for k in range(8):
            idx = i + offsets[k]
            if 0 <= idx < n:
                val = signal_arr[idx]
                valid_row_sum += val
                count += 1
                if use_robust:
                    if val < min_v: min_v = val
                    if val > max_v: max_v = val

        if count > 0:
            if use_robust and count > 2:
                valid_row_sum = valid_row_sum - min_v - max_v
                fAVG = valid_row_sum / (count - 2)
            else:
                fAVG = valid_row_sum / count

            raw_diff = abs(signal_arr[i] - fAVG)
            weight = count / 8.0
            if count < 8: weight *= edge_gain
            diff_arr[i] = raw_diff * weight
        else:
            diff_arr[i] = 0.0
    return diff_arr


# 10-bit PNG (2 bytes per pixel) -> 16-bit container
@jit(nopython=True, nogil=True, cache=True)
def _numba_restore_10bit(img_flat):
    n = len(img_flat)
    out = np.zeros(n, dtype=np.uint16)
    for i in range(n):
        val = img_flat[i]
        # High byte 8 bits + Low byte 2 bits
        png_h = (val & 0xff00) >> 6
        png_l = val & 0x3
        out[i] = png_h | png_l
    return out


# 14-bit (Similar logic)
@jit(nopython=True, nogil=True, cache=True)
def _numba_restore_14bit(img_flat):
    n = len(img_flat)
    out = np.zeros(n, dtype=np.uint16)
    factor = 16
    for i in range(n):
        val = img_flat[i]
        png_h = (val & 0xff00) >> 2
        png_l = val & 0x3f
        out[i] = (png_h | png_l) // factor
    return out


# ==============================================================================
# 🟢 2. LineDefectAlgorithm 类
# ==============================================================================
class LineDefectAlgorithm:

    # 🟢 [新增] 公开的还原接口，确保 UI 和 算法 使用同一套逻辑
    @staticmethod
    def restore_image(img_raw, effective_bits):
        h, w = img_raw.shape[:2]

        if effective_bits == 10:
            # 必须展平传给 Numba
            flat = img_raw.ravel()
            return _numba_restore_10bit(flat).reshape((h, w))

        elif effective_bits == 14:
            flat = img_raw.ravel()
            return _numba_restore_14bit(flat).reshape((h, w))

        elif effective_bits == 12:
            shift = 16 - 12
            return np.right_shift(img_raw, shift).astype(np.uint16)

        else:
            # 16-bit or 8-bit default
            return img_raw

    # 🟢 [新增] ROI 快速统计 (假设传入的 roi_img 已经是还原好的)
    @staticmethod
    def compute_roi_statistics(roi_img, params):
        ch_total = params.get('channel_count', 4)
        edge_gain = params.get('edge_gain', 1.0)
        use_robust = True if params.get('use_robust', 0) > 0 else False
        step = int(np.sqrt(ch_total))

        h, w = roi_img.shape
        full_row_diff = np.zeros(h, dtype=np.float32)
        full_row_avg = np.zeros(h, dtype=np.float32)
        full_col_diff = np.zeros(w, dtype=np.float32)
        full_col_avg = np.zeros(w, dtype=np.float32)

        for y in range(step):
            for x in range(step):
                sub = roi_img[y::step, x::step]
                if sub.size == 0: continue

                r_avg = np.mean(sub, axis=1).astype(np.float32)
                c_avg = np.mean(sub, axis=0).astype(np.float32)
                r_diff = _numba_calc_neighbor_diff_robust(r_avg, float(edge_gain), use_robust)
                c_diff = _numba_calc_neighbor_diff_robust(c_avg, float(edge_gain), use_robust)

                iy = np.arange(y, h, step)[:len(r_diff)]
                full_row_diff[iy] = np.maximum(full_row_diff[iy], r_diff)
                full_row_avg[iy] = r_avg

                ix = np.arange(x, w, step)[:len(c_diff)]
                full_col_diff[ix] = np.maximum(full_col_diff[ix], c_diff)
                full_col_avg[ix] = c_avg

        return {
            'row_diff': full_row_diff, 'row_avg': full_row_avg,
            'col_diff': full_col_diff, 'col_avg': full_col_avg
        }

    @staticmethod
    def run_inspection(img_input, params, is_preprocessed=False):
        # 1. 如果 UI 还没预处理，这里处理；如果已处理，跳过
        if not is_preprocessed:
            real_bits = params.get('effective_bits', 16)
            img_proc = LineDefectAlgorithm.restore_image(img_input, real_bits)
        else:
            img_proc = img_input

        # 2. 这里的逻辑与 compute_roi_statistics 类似，但增加了缺陷判定
        h, w = img_proc.shape[:2]
        ch_total = params.get('channel_count', 4)
        step = int(np.sqrt(ch_total))

        channels = []
        channel_offsets = []
        for y in range(step):
            for x in range(step):
                channels.append(img_proc[y::step, x::step])
                channel_offsets.append((y, x))

        raw_results = []
        row_max_stats = [];
        col_max_stats = []

        full_row_diff = np.zeros(h, dtype=np.float32)
        full_row_avg = np.zeros(h, dtype=np.float32)
        full_col_diff = np.zeros(w, dtype=np.float32)
        full_col_avg = np.zeros(w, dtype=np.float32)

        # Params extraction
        th_g_h = params.get('thresh_global_h', 10.0)
        th_g_v = params.get('thresh_global_v', 10.0)
        th_p_h = params.get('thresh_part_h', 5.0)
        th_p_v = params.get('thresh_part_v', 5.0)
        edge_gain = params.get('edge_gain', 1.0)
        use_robust = True if params.get('use_robust', 0) > 0 else False

        strip_h_sub = params.get('strip_h', 0) // step
        strip_v_sub = params.get('strip_v', 0) // step

        for ch_idx, ch_img in enumerate(channels):
            if ch_img.size == 0:
                row_max_stats.append(0);
                col_max_stats.append(0)
                continue

            y_off, x_off = channel_offsets[ch_idx]
            ch_h, ch_w = ch_img.shape

            row_avgs = np.mean(ch_img, axis=1).astype(np.float32)
            col_avgs = np.mean(ch_img, axis=0).astype(np.float32)

            # --- Row ---
            row_diffs = _numba_calc_neighbor_diff_robust(row_avgs, float(edge_gain), use_robust)
            if strip_h_sub > 0 and strip_h_sub * 2 < ch_h:
                row_diffs[:strip_h_sub] = 0;
                row_diffs[-strip_h_sub:] = 0

            iy = np.arange(y_off, h, step)[:len(row_diffs)]
            full_row_diff[iy] = np.maximum(full_row_diff[iy], row_diffs)
            full_row_avg[iy] = row_avgs
            row_max_stats.append(np.max(row_diffs) if len(row_diffs) else 0)

            bad_r = np.where(row_diffs > th_g_h)[0]
            if len(bad_r) > 100: bad_r = bad_r[:100]
            for ri in bad_r:
                raw_results.append({
                    'ch': ch_idx, 'type': 'Horizontal', 'mode': 'Global',
                    'index': ri * step + y_off, 'diff': row_diffs[ri]
                })

            # --- Col ---
            col_diffs = _numba_calc_neighbor_diff_robust(col_avgs, float(edge_gain), use_robust)
            if strip_v_sub > 0 and strip_v_sub * 2 < ch_w:
                col_diffs[:strip_v_sub] = 0;
                col_diffs[-strip_v_sub:] = 0

            ix = np.arange(x_off, w, step)[:len(col_diffs)]
            full_col_diff[ix] = np.maximum(full_col_diff[ix], col_diffs)
            full_col_avg[ix] = col_avgs
            col_max_stats.append(np.max(col_diffs) if len(col_diffs) else 0)

            bad_c = np.where(col_diffs > th_g_v)[0]
            if len(bad_c) > 100: bad_c = bad_c[:100]
            for ci in bad_c:
                raw_results.append({
                    'ch': ch_idx, 'type': 'Vertical', 'mode': 'Global',
                    'index': ci * step + x_off, 'diff': col_diffs[ci]
                })

            # --- Part ---
            block_n = params.get('block_qty', 10)
            if block_n > 0:
                bh, bw = ch_h // block_n, ch_w // block_n
                if bh > 8 and bw > 8:
                    for by in range(block_n):
                        for bx in range(block_n):
                            y0, y1 = by * bh, (by + 1) * bh
                            if strip_h_sub > 0:
                                if y1 <= strip_h_sub or y0 >= (ch_h - strip_h_sub): continue

                            sub_b = ch_img[y0:y1, bx * bw:(bx + 1) * bw]
                            sub_avg = np.mean(sub_b, 1).astype(np.float32)
                            sub_d = _numba_calc_neighbor_diff_robust(sub_avg, float(edge_gain), use_robust)

                            bad_sub = np.where(sub_d > th_p_h)[0]
                            for si in bad_sub:
                                gy = (y0 + si) * step + y_off
                                raw_results.append({
                                    'ch': ch_idx, 'type': 'Horizontal', 'mode': f'Part({by},{bx})',
                                    'index': gy, 'diff': sub_d[si]
                                })

        # Deduplicate: Global > Part, then Max Diff
        merged = {}
        for r in raw_results:
            k = (r['type'], r['index'])
            if k not in merged:
                merged[k] = r
            else:
                curr = merged[k]
                if r['mode'] == 'Global' and curr['mode'] != 'Global':
                    merged[k] = r
                elif r['mode'] != 'Global' and curr['mode'] == 'Global':
                    pass
                elif r['diff'] > curr['diff']:
                    merged[k] = r

        final_res = list(merged.values())
        final_res.sort(key=lambda x: (0 if x['mode'] == 'Global' else 1, x['index']))

        stats = {
            'row_diff': full_row_diff, 'row_avg': full_row_avg,
            'col_diff': full_col_diff, 'col_avg': full_col_avg,
            'row_max': row_max_stats, 'col_max': col_max_stats
        }
        return final_res, stats