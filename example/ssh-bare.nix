# A realistic NixOS openssh config with Nix module system
# semantics but NO HATC comments. Used to test the extractor.
{ config, lib, ... }:
{
  imports = [ ../network/firewall.nix ];

  services.openssh = {
    enable = lib.mkForce true;

    ports = [ 22 ];

    settings = lib.mkIf config.services.openssh.enable {
      PasswordAuthentication = lib.mkForce false;

      PermitRootLogin = lib.mkDefault "prohibit-password";

      Ciphers = [ "aes256-gcm@openssh.com" "chacha20-poly1305@openssh.com" ];

      X11Forwarding = lib.mkDefault false;

      UseDns = true;
    };

    openFirewall = true;
  };

  assertions = [{
    assertion = config.services.openssh.settings.PasswordAuthentication == false;
    message = "Password auth must be disabled for compliance";
  }];
}
