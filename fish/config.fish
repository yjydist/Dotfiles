set -U fish_greeting

if status is-interactive
    switch $TERM
        case xterm-ghostty xterm-kitty alacritty
            fastfetch
    end
end

#starship init fish | source
