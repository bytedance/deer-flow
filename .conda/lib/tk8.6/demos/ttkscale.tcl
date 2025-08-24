# ttkscale.tcl --
#
# This demonstration script shows an example with a horizontal scale.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .ttkscale
catch {destroy $w}
toplevel $w -bg [ttk::style lookup TLabel -background]
wm title $w "Themed Scale Demonstration"
wm iconname $w "ttkscale"
positionWindow $w

pack [ttk::frame [set w $w.contents]] -fill both -expand 1

ttk::label $w.msg -font $font -wraplength 3.5i -justify left -text "A label tied to a horizontal scale is displayed below.  If you click or drag mouse button 1 in the scale, you can change the contents of the label; a callback command is used to couple the slider to both the text and the coloring of the label."
pack $w.msg -side top -padx .5c

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons [winfo toplevel $w]]
pack $btns -side bottom -fill x

ttk::frame $w.frame -borderwidth 10
pack $w.frame -side top -fill x

# List of colors from rainbox; "Indigo" is not a standard color
set colorList {Red Orange Yellow Green Blue Violet}
ttk::label $w.frame.label
ttk::scale $w.frame.scale -from 0 -to 5 -command [list apply {{w idx} {
    set c [lindex $::colorList [tcl::mathfunc::int $idx]]
    $w.frame.label configure -foreground $c -text "Color: $c"
}} $w]
# Trigger the setting of the label's text
$w.frame.scale set 0
pack $w.frame.label $w.frame.scale
