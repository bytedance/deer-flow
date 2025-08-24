# ttknote.tcl --
#
# This demonstration script creates a toplevel window containing a Ttk
# notebook widget.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .ttknote
catch {destroy $w}
toplevel $w
wm title $w "Ttk Notebook Widget"
wm iconname $w "ttknote"
positionWindow $w

## See Code / Dismiss
pack [addSeeDismiss $w.seeDismiss $w] -side bottom -fill x

ttk::frame $w.f
pack $w.f -fill both -expand 1
set w $w.f

## Make the notebook and set up Ctrl+Tab traversal
ttk::notebook $w.note
pack $w.note -fill both -expand 1 -padx 2 -pady 3
ttk::notebook::enableTraversal $w.note

## Popuplate the first pane
ttk::frame $w.note.msg
ttk::label $w.note.msg.m -font $font -wraplength 4i -justify left -anchor n -text "Ttk is the new Tk themed widget set. One of the widgets it includes is the notebook widget, which provides a set of tabs that allow the selection of a group of panels, each with distinct content. They are a feature of many modern user interfaces. Not only can the tabs be selected with the mouse, but they can also be switched between using Ctrl+Tab when the notebook page heading itself is selected. Note that the second tab is disabled, and cannot be selected."
ttk::button $w.note.msg.b -text "Neat!" -underline 0 -command {
    set neat "Yeah, I know..."
    after 500 {set neat {}}
}
bind $w <Alt-n> "focus $w.note.msg.b; $w.note.msg.b invoke"
ttk::label $w.note.msg.l -textvariable neat
$w.note add $w.note.msg -text "Description" -underline 0 -padding 2
grid $w.note.msg.m - -sticky new -pady 2
grid $w.note.msg.b $w.note.msg.l -pady {2 4}
grid rowconfigure $w.note.msg 1 -weight 1
grid columnconfigure $w.note.msg {0 1} -weight 1 -uniform 1

## Populate the second pane. Note that the content doesn't really matter
ttk::frame $w.note.disabled
$w.note add $w.note.disabled -text "Disabled" -state disabled

## Popuplate the third pane
ttk::frame $w.note.editor
$w.note add $w.note.editor -text "Text Editor" -underline 0
text $w.note.editor.t -width 40 -height 10 -wrap char \
	-yscroll "$w.note.editor.s set"
ttk::scrollbar $w.note.editor.s -orient vertical -command "$w.note.editor.t yview"
pack $w.note.editor.s -side right -fill y -padx {0 2} -pady 2
pack $w.note.editor.t -fill both -expand 1 -pady 2 -padx {2 0}
