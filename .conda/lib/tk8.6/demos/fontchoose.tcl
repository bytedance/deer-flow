# fontchoose.tcl --
#
# Show off the stock font selector dialog

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .fontchoose
catch {destroy $w}
toplevel $w
wm title $w "Font Selection Dialog"
wm iconname $w "fontchooser"
positionWindow $w

catch {font create FontchooseDemoFont {*}[font actual TkDefaultFont]}

# The font chooser needs to be configured and then shown.
proc SelectFont {parent} {
    tk fontchooser configure -font FontchooseDemoFont \
        -command ApplyFont -parent $parent
    tk fontchooser show
}

proc ApplyFont {font} {
    font configure FontchooseDemoFont {*}[font actual $font]
}

# When the visibility of the fontchooser changes, the following event is fired
# to the parent widget.
#
bind $w <<TkFontchooserVisibility>> {
    if {[tk fontchooser configure -visible]} {
        %W.f.font state disabled
    } else {
        %W.f.font state !disabled
    }
}


set f [ttk::frame $w.f -relief sunken -padding 2]

text $f.msg -font FontchooseDemoFont -width 40 -height 6 -borderwidth 0 \
    -yscrollcommand [list $f.vs set]
ttk::scrollbar $f.vs -command [list $f.msg yview]

$f.msg insert end "Press the buttons below to choose a new font for the\
  text shown in this window.\n" {}

ttk::button $f.font -text "Set font ..." -command [list SelectFont $w]

grid $f.msg $f.vs -sticky news
grid $f.font -    -sticky e
grid columnconfigure $f 0 -weight 1
grid rowconfigure $f 0 -weight 1

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]

grid $f -sticky news
grid $btns -sticky ew
grid columnconfigure $w 0 -weight 1
grid rowconfigure $w 0 -weight 1
update idletasks
grid propagate $f 0
