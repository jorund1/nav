<table width="100%" class="mainWindow">
<tr><td class="mainWindowHead">
<p><?php echo gettext("Utstyrsgrupper"); ?></p>
</td></tr>

<tr><td>
<?php
include("loginordie.php");
loginOrDie();

echo "<p>";
echo gettext('Her kan du endre og opprette nye utstyrsgrupper. Utstyrsgruppene kan du koble direkte til varslinger inne i profilene.');

echo '<p><a href="#nygruppe">';
echo gettext("Legg til ny utstyrsgruppe") . "</a>";


session_set('lastaction', 'utstyr');
$brukernavn = session_get('bruker'); $uid = session_get('uid');

if ($subaction == 'endret') {

	if (post_get('gid') > 0) { 
            if (!$dbh->permissionEquipmentGroup( session_get('uid'), post_get('gid') ) ) {
                echo "<h2>Security violation</h2>";
                exit(0);
            }
		$dbh->endreUtstyrgruppe(post_get('gid'), post_get('navn'), post_get('descr') );
		unset($navn);
		unset($descr);
		print "<p><font size=\"+3\">" . gettext("OK</font>, utstyrsgruppenavnet er endret.");

	} else {
		print "<p><font size=\"+3\">" . gettext("Feil</font> oppstod, navnet er <b>ikke</b> endret.");
	}

	// Viser feilmelding om det har oppstått en feil.
	if ( $error != NULL ) {
		print $error->getHTML();
		$error = NULL;
	}
  
}

if ($subaction == 'slett') {

	if (get_get('gid') > 0) { 
            if (!$dbh->permissionEquipmentGroup( session_get('uid'), get_get('gid') ) ) {
                echo "<h2>Security violation</h2>";
                exit(0);
            }
        	
		$dbh->slettUtstyrgruppe(get_get('gid') );

		print "<p><font size=\"+3\">" . gettext("OK</font>, utstyrsgruppen er slettet fra databasen.");

	} else {
		print "<p><font size=\"+3\">" . gettext("Feil</font>, utstyrsgruppen er <b>ikke</b> slettet.");
	}

	// Viser feilmelding om det har oppstått en feil.
	if ( $error != NULL ) {
		print $error->getHTML();
		$error = NULL;
	}
  
}



if ($subaction == "nygruppe") {
	print "<h3>" . gettext("Registrerer ny utstyrsgruppe...") . "</h3>";
  
	$error = NULL;
	if ($navn == "") $navn = gettext("Uten navn");
        
	if ($uid > 0) { 
		$matchid = $dbh->nyUtstyrgruppe($uid, post_get('navn'), 
                    post_get('descr'), post_get('basertpaa') );
		print "<p><font size=\"+3\">" . gettext("OK</font>, en ny utstyrsgruppe er lagt til.");
    
	} else {
		print "<p><font size=\"+3\">" . gettext("Feil</font>, ny match er <b>ikke</b> lagt til i databasen.");
	}

	// Viser feilmelding om det har oppstått en feil.
	if ( $error != NULL ) {
		print $error->getHTML();
		$error = NULL;
	}
}


$l = new Lister( 112,
		array(gettext('Navn'), gettext('Eier'), gettext('#perioder'), gettext('#filtre'), gettext('Valg..')),
		 array(40, 10, 15, 15, 20),
		 array('left', 'left', 'right', 'right', 'right'),
		 array(true, true, true, true, false),
		 0 
);


print "<h3>" . gettext("Mine utstyrsgrupper") . "</h3>";

if ( get_exist('sortid') )
	$l->setSort(get_get('sort'), get_get('sortid') );

$utst = $dbh->listUtstyr($uid, $l->getSort() );

for ($i = 0; $i < sizeof($utst); $i++) {


  if ($utst[$i][2] > 0 ) 
    { $ap = $utst[$i][2]; }
  else 
    {
      $ap = "<img alt=\"Ingen\" src=\"icons/stop.gif\">";
    }
    
  if ($utst[$i][3] > 0 ) 
    { $af = $utst[$i][3]; }
  else 
    {
      $af = "<img alt=\"Ingen\" src=\"icons/stop.gif\">";
    }    

	if ($utst[$i][4] == 't' ) { 
		$eier = "<img alt=\"Min\" src=\"icons/person1.gif\">"; 
		$valg = '<a href="index.php?action=utstyrgrp&gid=' . $utst[$i][0]. 
			'">' . '<img alt="Open" src="icons/open2.gif" border=0></a>&nbsp;' .
			'<a href="index.php?subaction=endre&gid=' . 
			$utst[$i][0] .'#nygruppe">' .
			'<img alt="Edit" src="icons/edit.gif" border=0></a>&nbsp;' .
			'<a href="index.php?action=utstyr&subaction=slett&gid=' . 
			$utst[$i][0] . '">' .
			'<img alt="Delete" src="icons/delete.gif" border=0></a>';;
			
	} else {
		$eier = "<img alt=\"Gruppe\" src=\"icons/gruppe.gif\">";
		$valg = "&nbsp;";
    }

	$l->addElement( array("<p>" . $utst[$i][1],  // navn
		$eier, // type
		$ap, $af, // verdi
		$valg ) 
	);

	$inh = new HTMLCell("<p class=\"descr\">" . $utst[$i][5] . "</p>");	  
	$l->addElement (&$inh);
}

print $l->getHTML();

print "<p>[ <a href=\"index.php?action=" . $action. "&fid=" . $fid. "\">" . gettext("oppdater") . " <img src=\"icons/refresh.gif\" alt=\"oppdater\" border=0> ]</a> ";
print gettext("Antall filtre: ") . sizeof($utst);




if (! $subaction == 'endre') { $descr = gettext("Beskrivelse :"); }
?>

<a name="nygruppe"></a><p>
<?php
if ($subaction == 'endre') {
	print '<h2>' . gettext("Endre navn på utstyrsgruppe") . '</h2>';
} else {
	print '<h2>' . gettext("Legg til ny utstyrsgruppe") . '</h2>';
}
?>

<form name="form1" method="post" action="index.php?action=utstyr&subaction=<?php
if ($subaction == 'endre') echo "endret"; else echo "nygruppe";
?>">

<?php
if ($subaction == 'endre') {
	print '<input type="hidden" name="gid" value="' . get_get('gid') . '">';
	$old_values = $dbh->utstyrgruppeInfo( get_get('gid') );
}
?>
  <table width="100%" border="0" cellspacing="0" cellpadding="3">
   
    
    
    <tr>
    	<td width="30%"><p><?php echo gettext("Navn"); ?></p></td>
    	<td width="70%"><input name="navn" type="text" size="40" 
value="<?php echo $old_values[0]; ?>"></select>
        </td>
   </tr>

<?php
    if ($subaction != 'endre') {
        echo '<tr><td width="30%"><p>' . gettext("Basert på") . '</p></td>';
    	echo '<td width="70%">';
        
        $ilist = '<SELECT name="basertpaa">' . "\n";
        $ilist .= '<OPTION value="0">' . gettext("Tom utstyrsgruppe");

        $utstyrgrlist = $dbh->listUtstyr($uid, 1);
        if (count($utstyrgrlist) > 0) {
            foreach ($utstyrgrlist as $utstyrelement) {
                if ( $utstyrelement[4] ) {
                    $owner = "Min";
                } else {
                    $owner = "Arvet";
                }
        
                $ilist .= '<OPTION value="' . $utstyrelement[0] . '">' . 
                    $utstyrelement[1] . "  [" . $owner  . "]\n" ;
            }
        }
        $ilist .= '</SELECT>' . "\n";
	
        echo $ilist;
        
        echo '</select></td></tr>';
    }
?>

    <tr>
    	<td colspan="2"><textarea name="descr" cols="60" rows="4">
<?php 
if ($subaction == 'endre') {
    echo $old_values[1];
} else  {
    echo $descr;
}

 ?></textarea>  </td>
   </tr>

    <tr>
      <td>&nbsp;</td>
      <td align="right"><input type="submit" name="Submit" value="<?php
if ($subaction == 'endre') {
    echo gettext("Lagre endringer"); 
} else  {
    echo gettext("Legg til ny utstyrgruppe");
}
?>"></td>
    </tr>
  </table>

</form>


</td></tr>
</table>
