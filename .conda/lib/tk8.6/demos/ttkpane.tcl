# ttkpane.tcl --
#
# This demonstration script creates a Ttk pane with some content.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .ttkpane
catch {destroy $w}
toplevel $w
wm title $w "Themed Nested Panes"
wm iconname $w "ttkpane"
positionWindow $w

ttk::label $w.msg -font $font -wraplength 4i -justify left -text "This demonstration shows off a nested set of themed paned windows. Their sizes can be changed by grabbing the area between each contained pane and dragging the divider."
pack $w.msg [ttk::separator $w.msgSep] -side top -fill x

## See Code / Dismiss
pack [addSeeDismiss $w.seeDismiss $w] -side bottom -fill x

ttk::frame $w.f
pack $w.f -fill both -expand 1
set w $w.f
ttk::panedwindow $w.outer -orient horizontal
$w.outer add [ttk::panedwindow $w.outer.inLeft -orient vertical]
$w.outer add [ttk::panedwindow $w.outer.inRight -orient vertical]
$w.outer.inLeft  add [ttk::labelframe $w.outer.inLeft.top  -text Button]
$w.outer.inLeft  add [ttk::labelframe $w.outer.inLeft.bot  -text Clocks]
$w.outer.inRight add [ttk::labelframe $w.outer.inRight.top -text Progress]
$w.outer.inRight add [ttk::labelframe $w.outer.inRight.bot -text Text]
if {[tk windowingsystem] eq "aqua"} {
    foreach i [list inLeft.top inLeft.bot inRight.top inRight.bot] {
	$w.outer.$i configure -padding 3
    }
}

# Fill the button pane
ttk::button $w.outer.inLeft.top.b -text "Press Me" -command {
    tk_messageBox -type ok -icon info -message "Ouch!" -detail "That hurt..." \
	    -parent .ttkpane -title "Button Pressed"
}
pack $w.outer.inLeft.top.b -padx 2 -pady 5

# Fill the clocks pane
set i 0
proc every {delay script} {
    uplevel #0 $script
    after $delay [list every $delay $script]
}
set testzones {
    :Europe/Berlin
    :America/Argentina/Buenos_Aires
    :Africa/Johannesburg
    :Europe/London
    :America/Los_Angeles
    :Europe/Moscow
    :America/New_York
    :Asia/Singapore
    :Australia/Sydney
    :Asia/Tokyo
}
# Force a pre-load of all the timezones needed; otherwise can end up
# poor-looking synch problems!
set zones {}
foreach zone $testzones {
    if {![catch {clock format 0 -timezone $zone}]} {
        lappend zones $zone
    }
}
if {[llength $zones] < 2} { lappend zones -0200 :GMT :UTC +0200 }
foreach zone $zones {
    set city [string map {_ " "} [regexp -inline {[^/]+$} $zone]]
    if {$i} {
	pack [ttk::separator $w.outer.inLeft.bot.s$i] -fill x
    }
    ttk::label $w.outer.inLeft.bot.l$i -text $city -anchor w
    ttk::label $w.outer.inLeft.bot.t$i -textvariable time($zone) -anchor w
    pack $w.outer.inLeft.bot.l$i $w.outer.inLeft.bot.t$i -fill x
    every 1000 "set time($zone) \[clock format \[clock seconds\] -timezone $zone -format %T\]"
    incr i
}

# Fill the progress pane
ttk::progressbar $w.outer.inRight.top.progress -mode indeterminate
pack $w.outer.inRight.top.progress -fill both -expand 1
$w.outer.inRight.top.progress start

# Fill the text pane
if {[tk windowingsystem] ne "aqua"} {
    # The trick with the ttk::frame makes the text widget look like it fits with
    # the current Ttk theme despite not being a themed widget itself. It is done
    # by styling the frame like an entry, turning off the border in the text
    # widget, and putting the text widget in the frame with enough space to allow
    # the surrounding border to show through (2 pixels seems to be enough).
    ttk::frame $w.outer.inRight.bot.f				-style TEntry
    text $w.txt -wrap word -yscroll "$w.sb set" -width 30	-borderwidth 0
    pack $w.txt -fill both -expand 1 -in $w.outer.inRight.bot.f	-pady 2 -padx 2
    ttk::scrollbar $w.sb -orient vertical -command "$w.txt yview"
    pack $w.sb -side right -fill y -in $w.outer.inRight.bot
    pack $w.outer.inRight.bot.f -fill both -expand 1
    pack $w.outer -fill both -expand 1
} else {
    text $w.txt -wrap word -yscroll "$w.sb set" -width 30 -borderwidth 0
    ttk::scrollbar $w.sb -orient vertical -command "$w.txt yview"
    pack $w.sb -side right -fill y -in $w.outer.inRight.bot
    pack $w.txt -fill both -expand 1 -in $w.outer.inRight.bot
    pack $w.outer -fill both -expand 1 -padx 10 -pady {6 10}
}

