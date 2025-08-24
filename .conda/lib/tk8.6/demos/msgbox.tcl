# msgbox.tcl --
#
# This demonstration script creates message boxes of various type

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .msgbox
catch {destroy $w}
toplevel $w
wm title $w "Message Box Demonstration"
wm iconname $w "messagebox"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "Choose the icon and type option of the message box. Then press the \"Message Box\" button to see the message box."
pack $w.msg -side top

pack [addSeeDismiss $w.buttons $w {} {
    ttk::button $w.buttons.vars -text "Message Box" -command "showMessageBox $w"
}] -side bottom -fill x
#pack $w.buttons.dismiss $w.buttons.code $w.buttons.vars -side left -expand 1

frame $w.left
frame $w.right
pack $w.left $w.right -side left -expand yes -fill y  -pady .5c -padx .5c

label $w.left.label -text "Icon"
frame $w.left.sep -relief ridge -bd 1 -height 2
pack $w.left.label -side top
pack $w.left.sep -side top -fill x -expand no

set msgboxIcon info
foreach i {error info question warning} {
    radiobutton $w.left.b$i -text $i -variable msgboxIcon \
	-relief flat -value $i -width 16 -anchor w
    pack $w.left.b$i  -side top -pady 2 -anchor w -fill x
}

label $w.right.label -text "Type"
frame $w.right.sep -relief ridge -bd 1 -height 2
pack $w.right.label -side top
pack $w.right.sep -side top -fill x -expand no

set msgboxType ok
foreach t {abortretryignore ok okcancel retrycancel yesno yesnocancel} {
    radiobutton $w.right.$t -text $t -variable msgboxType \
	-relief flat -value $t -width 16 -anchor w
    pack $w.right.$t -side top -pady 2 -anchor w -fill x
}

proc showMessageBox {w} {
    global msgboxIcon msgboxType
    set button [tk_messageBox -icon $msgboxIcon -type $msgboxType \
	-title Message -parent $w\
	-message "This is a \"$msgboxType\" type messagebox with the \"$msgboxIcon\" icon"]

    tk_messageBox -icon info -message "You have selected \"$button\"" -type ok\
	-parent $w
}
