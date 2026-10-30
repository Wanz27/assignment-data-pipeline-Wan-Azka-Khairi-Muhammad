from pathlib import Path
import hashlib
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_PATH = BASE_DIR / "data" / "raw" / "automobileEDA_dirty_training.csv"
PROCESSED_PATH = BASE_DIR / "data" / "processed" / "automobileEDA_processed.csv"

#---------- Konstanta Konfigurasi ----------

# buat periksa nilai kolom untuk dibersihkan
CATEGORICAL_COLUMNS = [
    "make", "aspiration", "num-of-doors", "body-style", "drive-wheels",
    "engine-location", "engine-type", "num-of-cylinders", "fuel-system",
    "horsepower-binned",
]

# buat benerin typo merek
MAKE_TYPO_FIX = {"alfa-romero": "alfa-romeo", "peugot": "peugeot"}

# buat konversi angka
WORD_TO_NUM = {
    "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "eight": 8, "twelve": 12,
}

# buat transformasi
MINMAX_COLUMNS = ["curb-weight", "engine-size", "horsepower", "peak-rpm", "city-mpg", "highway-mpg"]
ONEHOT_COLUMNS = ["aspiration", "body-style", "drive-wheels", "engine-location", "engine-type", "fuel-system"]
HP_BIN_ORDER = {"Low": 0, "Medium": 1, "High": 2}

# buat template judul untuk setiap tahap pipeline
def section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def file_md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()

#---------- Tahap Extract ----------

def load_data(path=RAW_PATH):
    section("EXTRACT - Load Data")
    df = pd.read_csv(path)
    print(f"File   : {path.relative_to(BASE_DIR)}")
    print(f"Ukuran : {df.shape[0]} baris x {df.shape[1]} kolom")
    return df

#---------- Tahap Transform (Data Inspection) ----------

def inspect_data(df):
    section("TRANSFORM (1/3) - Data Inspection")

    print("\n[1] Lima baris pertama:")
    print(df.head().to_string())

    print(f"\n[2] Jumlah baris dan kolom: {df.shape[0]} baris, {df.shape[1]} kolom")

    print("\n[3] Nama kolom:")
    print(", ".join(df.columns))

    print("\n[4] Tipe data per kolom:")
    print(df.dtypes.to_string())

    missing = df.isna().sum()
    print("\n[5] Missing values per kolom:")
    print(missing[missing > 0].to_string())
    print(f"Total missing values: {missing.sum()}")

    n_dup = int(df.duplicated().sum())
    print(f"\n[6] Jumlah duplicate records: {n_dup}")
    if n_dup:
        print(df[df.duplicated(keep=False)].iloc[:, :6].to_string())

    print("\n[7] Nilai unik kolom kategorikal:")
    for col in CATEGORICAL_COLUMNS:
        values = df[col].value_counts(dropna=False).to_dict()
        print(f"  - {col} ({len(values)}): {values}")

    print("\n[8] Kolom dengan penulisan kategori tidak konsisten:")
    for col in CATEGORICAL_COLUMNS:
        raw = df[col].dropna().unique()
        normalized = pd.Series(raw).str.strip().str.lower().unique()
        if len(raw) != len(normalized):
            odd = [v for v in raw if v != v.strip().lower()]
            print(f"  - {col}: {odd}")

    print("\n[9] Format tanggal pada transaction_date:")
    patterns = df["transaction_date"].dropna().str.replace(r"\d", "9", regex=True)
    patterns = patterns.str.replace(r"[A-Za-z]{3}", "Mon", regex=True)
    for pattern, example in df["transaction_date"].dropna().groupby(patterns).first().items():
        print(f"  - {pattern:<12} contoh: {example}")

    print("\n[10] Ringkasan statistik kolom numerik:")
    print(df.describe().T[["count", "mean", "min", "max"]].to_string())

    return {"rows": len(df), "missing": missing, "duplicates": n_dup}

#---------- Tahap Transform (Data Cleaning) ----------

# menyamakan format tanggal
def parse_mixed_date(value):
    if pd.isna(value):
        return pd.NaT
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y", "%d-%b-%Y"):
        try:
            return pd.to_datetime(value, format=fmt)
        except ValueError:
            continue
    return pd.NaT

# mulai proses data cleaning
def clean_data(df):
    section("TRANSFORM (2/3) - Data Cleaning")

    before = df.copy()
    df = df.copy()
    rows_before = len(df)
    missing_before = int(df.isna().sum().sum())

    # menyeragamkan penulisan data
    for col in CATEGORICAL_COLUMNS:
        if col == "horsepower-binned":
            continue
        df[col] = df[col].str.strip().str.lower()
    df["make"] = df["make"].replace(MAKE_TYPO_FIX)
    print("[1] Menyeragamkan penulisan data: penggunaan strip untuk spasi dan lowercase pada setiap kolom")
    print(f"[2] Memperbaiki typo pada kolom 'make': {MAKE_TYPO_FIX}")

    # hapus data duplikat
    n_dup = int(df.duplicated().sum())
    df = df.drop_duplicates().reset_index(drop=True)
    print(f"[3] Menghapus {n_dup} baris duplikat")

    # hapus baris yang tdk punya nilai price
    n_no_price = int(df["price"].isna().sum())
    df = df.dropna(subset=["price"]).reset_index(drop=True)
    print(f"[4] Menghapus {n_no_price} baris yang tidak memiliki nilai 'price'")

    # seragamkan format tanggal dan interpolasi pada tanggal yg kosong
    df["transaction_date"] = df["transaction_date"].apply(parse_mixed_date)
    n_date_na = int(df["transaction_date"].isna().sum())
    as_int = df["transaction_date"].astype("int64").where(df["transaction_date"].notna())
    df["transaction_date"] = pd.to_datetime(as_int.interpolate().round(), unit="ns").dt.normalize()
    print(f"[5] Mengubah 'transaction_date' ke datetime (YYYY-MM-DD) dan menginterpolasi {n_date_na} tanggal yang kosong")

    # mengisi kolom 'make' yang kosong
    filled_make = 0
    for idx in df.index[df["make"].isna()]:
        prev_make = df["make"].iloc[idx - 1] if idx > 0 else None
        next_make = df["make"].iloc[idx + 1] if idx + 1 < len(df) else None
        if prev_make is not None and prev_make == next_make:
            df.loc[idx, "make"] = prev_make
            filled_make += 1
    df["make"] = df["make"].fillna("unknown")
    print(f"[6] mengisi {filled_make} kolom 'make' yang kosong jika nilai baris sebelum dan setelahnya sama, sisanya diisi dengan nilai 'unknown'")

    # mengisi kolom 'num-of-doors' yang kosong dengan modus data
    n_doord_na = int(df["num-of-doors"].isna().sum())
    df["num-of-doors"] = df.groupby("body-style")["num-of-doors"].transform(
        lambda x: x.fillna(x.mode().iloc[0])
    )
    print(f"[7] mengisi {n_doord_na} kolom 'num-of-doors' yang kosong dengan modus data berdasarkan 'body-style'") 

    # mengisi kolom 'horsepower' yang kosong berdasarkan median engine-size atau horsepower-binned
    n_hp_na = int(df["horsepower"].isna().sum())
    df["horsepower"] = df["horsepower"].fillna(df.groupby("engine-size")["horsepower"].transform("median"))
    df["horsepower"] = df["horsepower"].fillna(df.groupby("horsepower-binned")["horsepower"].transform("median"))
    print(f"[8] mengisi {n_hp_na} kolom 'horsepower' yang kosong berdasarkan median 'engine-size' atau 'horsepower-binned'")

    # mengisi kolom 'horsepower-binned' yang kosong berdasarkan batas max horsepower
    n_bin_na = int(df["horsepower-binned"].isna().sum())
    bin_max = df.groupby("horsepower-binned")["horsepower"].max()
    derived = np.select(
        [df["horsepower"] <= bin_max["Low"], df["horsepower"] <= bin_max["Medium"]],
        ["Low", "Medium"], default="High",
    )
    df["horsepower-binned"] = df["horsepower-binned"].fillna(pd.Series(derived, index=df.index))
    print(f"[9] mengisi {n_bin_na} kolom 'horsepower-binned' yang kosong berdasarkan batas max 'horsepower'")

    # mengisi kolom 'stroke' yang kosong berdasarkan median data
    n_stroke_na = int(df["stroke"].isna().sum())
    rotor_share = (df.loc[df["stroke"].isna(), "engine-type"] == "rotor").mean() if n_stroke_na else 0
    df["stroke"] = df["stroke"].fillna(df["stroke"].median())
    print(f"[10] mengisi {n_stroke_na} kolom 'stroke' yang kosong berdasarkan median data, dengan {rotor_share:.0%} di antaranya memiliki 'engine-type' rotor")

    # perbaiki tipe data angka yang ditulis string menjadi int
    for col in ["num-of-doors", "num-of-cylinders"]:
        df[col] = df[col].map(WORD_TO_NUM).astype("int64")
    print("[11] mengubah kolom 'num-of-doors' dan 'num-of-cylinders' dari string ke int")

    # periksa nilai tidak wajar
    positive_cols = ["wheel-base", "length", "width", "height", "curb-weight", "engine-size",
                     "bore", "stroke", "horsepower", "peak-rpm", "city-mpg", "highway-mpg", "price"]
    invalid = int((df[positive_cols] <= 0).sum().sum())
    fuel_conflict = int(((df["diesel"] + df["gas"]) != 1).sum())
    print(f"[12] memeriksa nilai tidak wajar: {invalid} nilai <= 0 pada kolom numerik, {fuel_conflict} baris memiliki konflik fuel-type (terdapat mobil yang berjenis diesel dan gas)")
    
    q1, q3 = df["price"].quantile([0.25, 0.75])
    n_outlier = int((df["price"] > q3 + 1.5 * (q3 - q1)).sum())
    print(f"[13] memeriksa outlier pada kolom 'price': {n_outlier} baris memiliki harga di atas outlier (mobil mewah)")

    # ringkasan perubahan
    print("\nHasil perubahan setelah data cleaning:")
    print(f"  Jumlah baris       : {rows_before} -> {len(df)}")
    print(f"  Total missing value: {missing_before} -> {int(df.isna().sum().sum())}")
    print(f"  Duplikat dihapus   : {n_dup}")
    print("\nMissing values per kolom (sebelum -> sesudah):")
    miss_b, miss_a = before.isna().sum(), df.isna().sum()
    for col in miss_b[miss_b > 0].index:
        print(f"  - {col:<18}: {miss_b[col]} -> {miss_a[col]}")

    changed = changed_columns(before.drop_duplicates().dropna(subset=["price"]).reset_index(drop=True), df)
    print("\nKolom yang mengalami perubahan nilai/tipe:")
    for col, (n, dtype_b, dtype_a) in changed.items():
        print(f"  - {col:<18}: {n:>3} sel berubah, dtype {dtype_b} -> {dtype_a}")
    return df

# bandingkan dua dataframe, lalu mengembalikan kolom yang berubah
def changed_columns(before, after):
    result = {}
    for col in after.columns:
        b, a = before[col].astype(str), after[col].astype(str)
        n = int((b != a).sum())
        if n or before[col].dtype != after[col].dtype:
            result[col] = (n, before[col].dtype, after[col].dtype)
    return result

#---------- Tahap Transform (Data Transformation) ----------

def min_max_scale(series):
    return (series - series.min()) / (series.max() - series.min())

def transform_data(df):
    section("TRANSFORM (3/3) - Data Transformation")
    df = df.copy()

    # min-max scaling
    for col in MINMAX_COLUMNS:
        df[f"{col}_scaled"] = min_max_scale(df[col]).round(6)
    print(f"[1] Min-Max scaling: {MINMAX_COLUMNS}")
    print("    Contoh sebelum vs sesudah:")
    sample_columns = [c for col in MINMAX_COLUMNS[:3] for c in (col, f"{col}_scaled")]
    print(df[sample_columns].head().to_string())

    # ordinal encoding
    df["horsepower-binned_encoded"] = df["horsepower-binned"].map(HP_BIN_ORDER).astype("int64")
    print("\n[2] Ordinal encoding horsepower-binned:", HP_BIN_ORDER)
    print(df[["horsepower-binned", "horsepower-binned_encoded"]].drop_duplicates().to_string(index=False))

    # frequency encoding
    df["make_freq"] = df["make"].map(df["make"].value_counts(normalize=True)).round(6)
    print("\n[3] Frequency encoding make (proporsi kemunculan merek):")
    print(df[["make", "make_freq"]].drop_duplicates().head().to_string(index=False))

    # one-hot encoding
    before_columns = set(df.columns)
    sample = df[ONEHOT_COLUMNS[:3]].head(3).copy()
    df = pd.get_dummies(df, columns=ONEHOT_COLUMNS, dtype="int64")
    new_columns = [c for c in df.columns if c not in before_columns]
    print(f"\n[4] One-hot encoding {ONEHOT_COLUMNS} -> {len(new_columns)} kolom biner baru")
    print("    Contoh sebelum:")
    print(sample.to_string())
    print("    Contoh sesudah (kolom body-style_*):")
    print(df[[c for c in new_columns if c.startswith("body-style_")]].head(3).to_string())

    # menyimpan tanggal dalam format ISO
    df["transaction_date"] = df["transaction_date"].dt.strftime("%Y-%m-%d")

    print(f"\nUkuran setelah transformasi: {df.shape[0]} baris x {df.shape[1]} kolom")
    return df

#---------- Tahap Load ----------

def save_data(df, path=PROCESSED_PATH):
    section("LOAD - Save Processed Dataset")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Tersimpan di: {path.relative_to(BASE_DIR)} ({df.shape[0]} baris x {df.shape[1]} kolom)")

def run_pipeline():
    raw_hash = file_md5(RAW_PATH)

    raw_df = load_data()                 # Extract
    inspect_data(raw_df)                 # Transform: inspection
    clean_df = clean_data(raw_df)        # Transform: cleaning
    final_df = transform_data(clean_df)  # Transform: transformation
    save_data(final_df)                  # Load

    section("SELESAI")
    unchanged = file_md5(RAW_PATH) == raw_hash
    print(f"Dataset mentah tidak berubah (MD5 sama): {unchanged}")
    print(f"Raw {raw_df.shape} -> Clean {clean_df.shape} -> Processed {final_df.shape}")
    return final_df


if __name__ == "__main__":
    run_pipeline()
