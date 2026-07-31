{
  lib,
  stdenvNoCC,
  coreutils,
  fetchFromGitHub,
  haxe,
  makeWrapper,
  neko,
  python3,
  writeShellScript,
}:

let
  converterSrc = fetchFromGitHub {
    owner = "YAL-Tools";
    repo = "vial-to-keymap-drawer";
    rev = "fb1af9de01ff7edc8bf0230e65c84e40645503ad";
    hash = "sha256-e2p0QjYe6rs782tbusfDkU8BowtQ6V0UFFqSyE9KVng=";
  };
  keyballSrc = fetchFromGitHub {
    owner = "Yowkees";
    repo = "keyball";
    rev = "78de67c49f38836aca06bccd87b42d297d89e1b4";
    hash = "sha256-OcTDPL7ZgSQIrtVcOPF9Np+rvKDfDLAXwqPEstjw+Bk=";
  };
  keyball39Geometry = "${keyballSrc}/qmk_firmware/keyboards/keyball/keyball39/info.json";
  keyball44Geometry = "${keyballSrc}/qmk_firmware/keyboards/keyball/keyball44/info.json";
  wrapper = writeShellScript "vial-converter" ''
    set -euo pipefail

    usage() {
      printf '%s\n' \
        'Usage: vial-converter --model <slug> --geometry <path> --input <vil> --output <yaml>' \
        "" \
        'Supported models: keyball39, keyball44' \
        'Pinned geometry paths:' \
        '  keyball39: ${keyball39Geometry}' \
        '  keyball44: ${keyball44Geometry}'
    }

    if [[ ''${1:-} == "--help" || ''${1:-} == "-h" ]]; then
      usage
      exit 0
    fi

    model=""
    geometry=""
    input=""
    output=""
    while (( $# > 0 )); do
      case "$1" in
        --model|--geometry|--input|--output)
          if (( $# < 2 )); then
            printf 'vial-converter: %s requires a value\n' "$1" >&2
            usage >&2
            exit 2
          fi
          case "$1" in
            --model) model="$2" ;;
            --geometry) geometry="$2" ;;
            --input) input="$2" ;;
            --output) output="$2" ;;
          esac
          shift 2
          ;;
        *)
          printf 'vial-converter: unknown argument: %s\n' "$1" >&2
          usage >&2
          exit 2
          ;;
      esac
    done

    if [[ -z "$model" || -z "$geometry" || -z "$input" || -z "$output" ]]; then
      printf 'vial-converter: all four options are required\n' >&2
      usage >&2
      exit 2
    fi

    case "$model" in
      keyball39|keyball44) keyboard="keyball/$model" ;;
      *)
        printf 'vial-converter: unsupported model: %s\n' "$model" >&2
        exit 2
        ;;
    esac

    if [[ ! -f "$geometry" ]]; then
      printf 'vial-converter: geometry does not exist: %s\n' "$geometry" >&2
      exit 2
    fi
    if [[ ! -f "$input" ]]; then
      printf 'vial-converter: input does not exist: %s\n' "$input" >&2
      exit 2
    fi

    temporary="$(${lib.getExe' coreutils "mktemp"})"
    trap '${lib.getExe' coreutils "rm"} -f "$temporary"' EXIT
    "${lib.getExe' neko "neko"}" "$VIAL_CONVERTER_PROGRAM" \
      --keyboard "$keyboard" \
      --vil "$input" \
      "$temporary"

    "${lib.getExe python3}" -c '
import json
import pathlib
import sys

geometry, source_name, output_name = sys.argv[1:]
source = pathlib.Path(source_name).read_text()
lines = source.splitlines(keepends=True)
if not lines or not lines[0].startswith("layout: "):
    raise SystemExit("vial-converter: converter output has no layout header")
lines[0] = "layout: {qmk_info_json: " + json.dumps(geometry) + "}\n"
for index, line in enumerate(lines[1:], start=1):
    brace = line.find("{")
    if brace < 0:
        continue
    candidate = line[brace:].rstrip("\r\n")
    if not candidate.endswith("}"):
        continue
    value = json.loads(candidate)
    if not isinstance(value, dict):
        continue
    value = {key: item for key, item in value.items() if item is not None}
    lines[index] = line[:brace] + json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    ) + "\n"
pathlib.Path(output_name).write_text("".join(lines))
' "$geometry" "$temporary" "$output"
  '';
in
stdenvNoCC.mkDerivation {
  pname = "vial-converter";
  version = "unstable-2026-04-21";

  src = converterSrc;

  nativeBuildInputs = [ haxe makeWrapper ];

  buildPhase = ''
    runHook preBuild
    haxe build-neko.hxml
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    install -Dm644 bin/VialToKeymapDrawer.n "$out/libexec/VialToKeymapDrawer.n"
    install -Dm755 ${wrapper} "$out/bin/vial-converter"
    wrapProgram "$out/bin/vial-converter" \
      --set VIAL_CONVERTER_PROGRAM "$out/libexec/VialToKeymapDrawer.n"
    runHook postInstall
  '';

  passthru.geometryPaths = {
    keyball39 = keyball39Geometry;
    keyball44 = keyball44Geometry;
  };

  meta = {
    description = "Pinned Vial to keymap-drawer converter";
    homepage = "https://github.com/YAL-Tools/vial-to-keymap-drawer";
    license = lib.licenses.gpl2Only;
    mainProgram = "vial-converter";
    platforms = [ "x86_64-linux" ];
  };
}
