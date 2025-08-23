import argparse, pathlib
from rjsmin import jsmin


def minify_file(src_path: pathlib.Path, dst_path: pathlib.Path):
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with src_path.open("r", encoding="utf-8") as f:
        code = f.read()
    with dst_path.open("w", encoding="utf-8") as f:
        f.write(jsmin(code))


def main():
    p = argparse.ArgumentParser(description="Minify JS with rjsmin")
    p.add_argument("inputs", nargs="+", help="JS files or directories")
    p.add_argument("-o", "--out", default="dist", help="Output dir for minified files")
    args = p.parse_args()

    out_root = pathlib.Path(args.out)
    for inp in args.inputs:
        pth = pathlib.Path(inp)
        if pth.is_dir():
            for src in pth.rglob("*.js"):
                rel = src.relative_to(pth)
                dst = out_root / rel.with_suffix(".min.js")
                minify_file(src, dst)
        else:
            src = pth
            dst = out_root / src.name.replace(".js", ".min.js")
            minify_file(src, dst)


if __name__ == "__main__":
    main()