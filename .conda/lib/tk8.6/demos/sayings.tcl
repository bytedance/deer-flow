# sayings.tcl --
#
# This demonstration script creates a listbox that can be scrolled
# both horizontally and vertically.  It displays a collection of
# well-known sayings.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .sayings
catch {destroy $w}
toplevel $w
wm title $w "Listbox Demonstration (well-known sayings)"
wm iconname $w "sayings"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "The listbox below contains a collection of well-known sayings.  You can scan the list using either of the scrollbars or by dragging in the listbox window with button 2 pressed."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

frame $w.frame -borderwidth 10
pack $w.frame -side top -expand yes -fill both -padx 1c


ttk::scrollbar $w.frame.yscroll -command "$w.frame.list yview"
ttk::scrollbar $w.frame.xscroll -orient horizontal \
    -command "$w.frame.list xview"
listbox $w.frame.list -width 20 -height 10 -setgrid 1 \
    -yscroll "$w.frame.yscroll set" -xscroll "$w.frame.xscroll set"

grid $w.frame.list -row 0 -column 0 -rowspan 1 -columnspan 1 -sticky news
grid $w.frame.yscroll -row 0 -column 1 -rowspan 1 -columnspan 1 -sticky news
grid $w.frame.xscroll -row 1 -column 0 -rowspan 1 -columnspan 1 -sticky news
grid rowconfig    $w.frame 0 -weight 1 -minsize 0
grid columnconfig $w.frame 0 -weight 1 -minsize 0


$w.frame.list insert 0 "Don't speculate, measure" "Waste not, want not" "Early to bed and early to rise makes a man healthy, wealthy, and wise" "Ask not what your country can do for you, ask what you can do for your country" "I shall return" "NOT" "A picture is worth a thousand words" "User interfaces are hard to build" "Thou shalt not steal" "A penny for your thoughts" "Fool me once, shame on you;  fool me twice, shame on me" "Every cloud has a silver lining" "Where there's smoke there's fire" "It takes one to know one" "Curiosity killed the cat" "Take this job and shove it" "Up a creek without a paddle" "I'm mad as hell and I'm not going to take it any more" "An apple a day keeps the doctor away" "Don't look a gift horse in the mouth" "Measure twice, cut once"
