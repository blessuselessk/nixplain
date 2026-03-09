#! hardened remote deployment target
{ config, lib, ... }:
{
  #! minimal attack surface SSH
  services.openssh = {
    #>> settings|openFirewall
    enable = true;

    #| ***22|2222|443
    #> openFirewall
    #> ../network/firewall.nix:networking.firewall.allowedTCPPorts
    ports = [ 22 ];

    settings = {
      #= by:security-team | for:SOC2-CC6.1
      #<> PermitRootLogin
      #<< enable
      #| ***false|true
      PasswordAuthentication = false;

      #= by:security-team | for:SOC2-CC6.1
      #| *prohibit-password|no|forced-commands-only|**yes
      #<> PasswordAuthentication
      #<< enable
      PermitRootLogin = "prohibit-password";

      #= by:crypto-team | for:FIPS-140-2
      Ciphers = [ "aes256-gcm@openssh.com" "chacha20-poly1305@openssh.com" ];

      #? preference — toggle for debugging
      #>< ForwardAgent
      #| *false|**true
      X11Forwarding = false;

      #? by:anyone
      #~ disabled per team preference, not a security requirement
      #| *true|**false
      UseDns = true;
    };

    #<< enable
    #< ports
    #> ../network/firewall.nix:networking.firewall.allowedTCPPorts
    openFirewall = true;
  };
}
