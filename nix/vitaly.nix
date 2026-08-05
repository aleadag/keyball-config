{
  lib,
  rustPlatform,
  fetchFromGitHub,
  pkg-config,
  udev,
}:

rustPlatform.buildRustPackage rec {
  pname = "vitaly";
  version = "0.1.32";

  src = fetchFromGitHub {
    owner = "bskaplou";
    repo = "vitaly";
    rev = "7ba52b0cf121e411434adcebf111e54b0ee470eb";
    hash = "sha256-u1OmH2AeskcjNB1ac6iSBaA0Xyea+tB8f5F/LCzafj4=";
  };

  patches = [ ./vitaly-save-definition.patch ];

  cargoHash = "sha256-HBJFOi3KrjIepGaPwtv/39sQotvQPae9y2rdPJ/uQ8k=";

  nativeBuildInputs = [ pkg-config ];
  buildInputs = [ udev ];

  meta = {
    description = "VIA/Vial API client and CLI tool";
    homepage = "https://github.com/bskaplou/vitaly";
    license = lib.licenses.mit;
    mainProgram = "vitaly";
    platforms = [ "x86_64-linux" ];
  };
}
