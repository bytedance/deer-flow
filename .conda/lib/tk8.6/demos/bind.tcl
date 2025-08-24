# bind.tcl --
#
# This demonstration script creates a text widget with bindings set
# up for hypertext-like effects.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .bind
catch {destroy $w}
toplevel $w
wm title $w "Text Demonstration - Tag Bindings"
wm iconname $w "bind"
positionWindow $w

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

text $w.text -yscrollcommand "$w.scroll set" -setgrid true \
	-width 60 -height 24 -font $font -wrap word
ttk::scrollbar $w.scroll -command "$w.text yview"
pack $w.scroll -side right -fill y
pack $w.text -expand yes -fill both

# Set up display styles.

if {[winfo depth $w] > 1} {
    set bold "-background #43ce80 -relief raised -borderwidth 1"
    set normal "-background {} -relief flat"
} else {
    set bold "-foreground white -background black"
    set normal "-foreground {} -background {}"
}

# Add text to widget.

$w.text insert 0.0 {\
The same tag mechanism that controls display styles in text widgets can also be used to associate Tcl commands with regions of text, so that mouse or keyboard actions on the text cause particular Tcl commands to be invoked.  For example, in the text below the descriptions of the canvas demonstrations have been tagged.  When you move the mouse over a demo description the description lights up, and when you press button 1 over a description then that particular demonstration is invoked.

}
$w.text insert end \
{1. Samples of all the different types of items that can be created in canvas widgets.} d1
$w.text insert end \n\n
$w.text insert end \
{2. A simple two-dimensional plot that allows you to adjust the positions of the data points.} d2
$w.text insert end \n\n
$w.text insert end \
{3. Anchoring and justification modes for text items.} d3
$w.text insert end \n\n
$w.text insert end \
{4. An editor for arrow-head shapes for line items.} d4
$w.text insert end \n\n
$w.text insert end \
{5. A ruler with facilities for editing tab stops.} d5
$w.text insert end \n\n
$w.text insert end \
{6. A grid that demonstrates how canvases can be scrolled.} d6

# Create bindings for tags.

foreach tag {d1 d2 d3 d4 d5 d6} {
    $w.text tag bind $tag <Enter> "$w.text tag configure $tag $bold"
    $w.text tag bind $tag <Leave> "$w.text tag configure $tag $normal"
}
# Main widget program sets variable tk_demoDirectory
$w.text tag bind d1 <Button-1> {source -encoding utf-8 [file join $tk_demoDirectory items.tcl]}
$w.text tag bind d2 <Button-1> {source -encoding utf-8 [file join $tk_demoDirectory plot.tcl]}
$w.text tag bind d3 <Button-1> {source -encoding utf-8 [file join $tk_demoDirectory ctext.tcl]}
$w.text tag bind d4 <Button-1> {source -encoding utf-8 [file join $tk_demoDirectory arrow.tcl]}
$w.text tag bind d5 <Button-1> {source -encoding utf-8 [file join $tk_demoDirectory ruler.tcl]}
$w.text tag bind d6 <Button-1> {source -encoding utf-8 [file join $tk_demoDirectory cscroll.tcl]}

$w.text mark set insert 0.0
$w.text configure -state disabled
