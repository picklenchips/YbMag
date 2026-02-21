import argparse, os, csv, numpy as np
import matplotlib.pyplot as plt

INTEN_KEYS = {"intensity","intens","value","gray","grey","luminance","I","mean","val"}

def read_csv_auto(path):
    # Try header first
    with open(path, "r", newline="") as f:
        snif = f.read(2048)
        f.seek(0)
        dialect = csv.Sniffer().sniff(snif, delimiters=",;\t")
        has_header = csv.Sniffer().has_header(snif)
        reader = csv.reader(f, dialect)
        rows = list(reader)

    if not rows:
        raise RuntimeError("Empty CSV")

    # If header present, map columns by name; else treat as numeric table and take last numeric col
    start = 1 if has_header else 0
    header = [h.strip().lower() for h in rows[0]] if has_header else None

    # Build numeric columns
    cols = list(zip(*rows[start:]))
    def to_num(col):
        out=[]
        for v in col:
            try: out.append(float(v))
            except: out.append(np.nan)
        return np.array(out, dtype=float)

    num_cols = [to_num(c) for c in cols]
    # Choose intensity column
    if header:
        # prefer any header containing typical intensity keys
        scores = []
        for i, name in enumerate(header):
            score = 0
            for k in INTEN_KEYS:
                if k in name: score += 1
            # prefer columns that are mostly numeric
            numeric_frac = np.isfinite(num_cols[i]).mean()
            score += numeric_frac
            scores.append((score, i))
        idx = max(scores)[1]  # best match
    else:
        # no header: choose the last column that is mostly numeric
        numeric_scores = [(np.isfinite(c).mean(), i) for i, c in enumerate(num_cols)]
        idx = max(numeric_scores)[1]

    inten = num_cols[idx]
    inten = inten[np.isfinite(inten)]
    if inten.size == 0:
        raise RuntimeError("No numeric intensity column detected.")

    return inten

def metrics(inten):
    x = inten.astype(float)
    finite = x[np.isfinite(x)]
    if finite.size == 0:
        return None
    cnt = finite.size
    mn, mx = float(np.min(finite)), float(np.max(finite))
    mean, std = float(np.mean(finite)), float(np.std(finite))
    p1,p5,p25,p50,p75,p95,p99 = np.percentile(finite,[1,5,25,50,75,95,99])
    pos = finite[finite>0]
    dr_db = float(20*np.log10(pos.max()/pos.min())) if pos.size else 0.0
    return dict(count=cnt,min=mn,max=mx,mean=mean,std=std,
                p1=float(p1),p5=float(p5),p25=float(p25),p50=float(p50),
                p75=float(p75),p95=float(p95),p99=float(p99),dyn_range_db=dr_db,
                intensities=finite)

def save_hist(intens, out_png):
    plt.figure()
    plt.hist(intens, bins=256)
    plt.title("Intensity histogram")
    plt.xlabel("value"); plt.ylabel("count")
    plt.tight_layout(); plt.savefig(out_png, dpi=120); plt.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--outdir", default="./analysis_out")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    inten = read_csv_auto(args.csv)
    res = metrics(inten)
    print(f"[auto] {args.csv}")
    for k in ["count","min","max","mean","std","p1","p5","p25","p50","p75","p95","p99","dyn_range_db"]:
        print(f"{k:>12}: {res[k]:.6g}" if isinstance(res[k], float) else f"{k:>12}: {res[k]}")
    out_png = os.path.join(args.outdir, "histogram.png")
    save_hist(res["intensities"], out_png)
    print(f"Saved {out_png}")

if __name__ == "__main__":
    main()
