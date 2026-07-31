{
  description = "Pinned Keyball configuration toolchain";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      vitaly = pkgs.callPackage ./nix/vitaly.nix { };
      vialConverter = pkgs.callPackage ./nix/vial-converter.nix { };
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = [ vitaly vialConverter pkgs.keymap-drawer pkgs.python3 ];
      };

      packages.${system} = {
        inherit vitaly vialConverter;
        default = vialConverter;
      };
    };
}
