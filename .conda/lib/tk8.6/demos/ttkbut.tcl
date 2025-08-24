# ttkbut.tcl --
#
# This demonstration script creates a toplevel window containing several
# simple Ttk widgets, such as labels, labelframes, buttons, checkbuttons and
# radiobuttons.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .ttkbut
catch {destroy $w}
toplevel $w
wm title $w "Simple Ttk Widgets"
wm iconname $w "ttkbut"
positionWindow $w

ttk::label $w.msg -font $font -wraplength 4i -justify left -text "Ttk is the new Tk themed widget set. This is a Ttk themed label, and below are three groups of Ttk widgets in Ttk labelframes. The first group are all buttons that set the current application theme when pressed. The second group contains three sets of checkbuttons, with a separator widget between the sets. Note that the \u201cEnabled\u201d button controls whether all the other themed widgets in this toplevel are in the disabled state. The third group has a collection of linked radiobuttons."
pack $w.msg -side top -fill x

## See Code / Dismiss
pack [addSeeDismiss $w.seeDismiss $w {enabled cheese tomato basil oregano happiness}]\
	-side bottom -fill x

## Add buttons for setting the theme
ttk::labelframe $w.buttons -text "Buttons"
foreach theme [ttk::themes] {
    ttk::button $w.buttons.$theme -text $theme \
	    -command [list ttk::setTheme $theme]
    pack $w.buttons.$theme -pady 2
}

## Helper procedure for the top checkbutton
proc setState {rootWidget exceptThese value} {
    if {$rootWidget in $exceptThese} {
	return
    }
    ## Non-Ttk widgets (e.g. the toplevel) will fail, so make it silent
    catch {
	$rootWidget state $value
    }
    ## Recursively invoke on all children of this root that are in the same
    ## toplevel widget
    foreach w [winfo children $rootWidget] {
	if {[winfo toplevel $w] eq [winfo toplevel $rootWidget]} {
	    setState $w $exceptThese $value
	}
    }
}

## Set up the checkbutton group
ttk::labelframe $w.checks -text "Checkbuttons"
ttk::checkbutton $w.checks.e  -text Enabled -variable enabled -command {
    setState .ttkbut .ttkbut.checks.e \
	    [expr {$enabled ? "!disabled" : "disabled"}]
}
set enabled 1
## See ttk_widget(n) for other possible state flags
ttk::separator   $w.checks.sep1
ttk::checkbutton $w.checks.c1 -text Cheese  -variable cheese
ttk::checkbutton $w.checks.c2 -text Tomato  -variable tomato
ttk::separator   $w.checks.sep2
ttk::checkbutton $w.checks.c3 -text Basil   -variable basil
ttk::checkbutton $w.checks.c4 -text Oregano -variable oregano
pack $w.checks.e $w.checks.sep1 $w.checks.c1 $w.checks.c2 $w.checks.sep2 \
	$w.checks.c3 $w.checks.c4   -fill x -pady 2

## Set up the radiobutton group
ttk::labelframe $w.radios -text "Radiobuttons"
ttk::radiobutton $w.radios.r1 -text "Great" -variable happiness -value great
ttk::radiobutton $w.radios.r2 -text "Good" -variable happiness -value good
ttk::radiobutton $w.radios.r3 -text "OK" -variable happiness -value ok
ttk::radiobutton $w.radios.r4 -text "Poor" -variable happiness -value poor
ttk::radiobutton $w.radios.r5 -text "Awful" -variable happiness -value awful
pack $w.radios.r1 $w.radios.r2 $w.radios.r3 $w.radios.r4 $w.radios.r5 \
	-fill x -padx 3 -pady 2

## Arrange things neatly
pack [ttk::frame $w.f] -fill both -expand 1
lower $w.f
grid $w.buttons $w.checks $w.radios -in $w.f -sticky nwe -pady 2 -padx 3
grid columnconfigure $w.f {0 1 2} -weight 1 -uniform yes
