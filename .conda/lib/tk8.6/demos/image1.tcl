# image1.tcl --
#
# This demonstration script displays two image widgets.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .image1
catch {destroy $w}
toplevel $w
wm title $w "Image Demonstration #1"
wm iconname $w "Image1"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "This demonstration displays two images, each in a separate label widget."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

# Main widget program sets variable tk_demoDirectory
catch {image delete image1a}
image create photo image1a -file [file join $tk_demoDirectory images earth.gif]
label $w.l1 -image image1a -bd 1 -relief sunken

catch {image delete image1b}
image create photo image1b \
	-file [file join $tk_demoDirectory images earthris.gif]
label $w.l2 -image image1b -bd 1 -relief sunken

pack $w.l1 $w.l2 -side top -padx .5m -pady .5m
