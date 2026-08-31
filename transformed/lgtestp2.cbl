      ******************************************************************
      *                                                                *
      * (C) Copyright IBM Corp. 2011, 2020                             *
      *                                                                *
      *                Endowment Policy Menu                           *
      *                                                                *
      * Menu for Endowment Policy Transactions                         *
      *                                                                *
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LGTESTP2.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
      *
       DATA DIVISION.
       WORKING-STORAGE SECTION.

       77 MSGEND                       PIC X(24) VALUE
                                        'Transaction ended      '.

      * >>> BEGIN COPY SSMAP (ssmap.bms>)
      *****************************************************************
      * SYMBOLIC MAP generated from BMS source by cobol_transformer.  *
      * Layout follows the standard DFHMSD TYPE=DSECT expansion.      *
      *****************************************************************
       01  SSMAPC1I.
           02  FILLER PIC X(12).
           02  ENT1CNOL    COMP PIC S9(4).
           02  ENT1CNOF    PIC X.
           02  FILLER REDEFINES ENT1CNOF.
               03  ENT1CNOA    PIC X.
           02  ENT1CNOI    PIC X(10).
           02  ENT1FNAL    COMP PIC S9(4).
           02  ENT1FNAF    PIC X.
           02  FILLER REDEFINES ENT1FNAF.
               03  ENT1FNAA    PIC X.
           02  ENT1FNAI    PIC X(10).
           02  ENT1LNAL    COMP PIC S9(4).
           02  ENT1LNAF    PIC X.
           02  FILLER REDEFINES ENT1LNAF.
               03  ENT1LNAA    PIC X.
           02  ENT1LNAI    PIC X(20).
           02  ENT1DOBL    COMP PIC S9(4).
           02  ENT1DOBF    PIC X.
           02  FILLER REDEFINES ENT1DOBF.
               03  ENT1DOBA    PIC X.
           02  ENT1DOBI    PIC X(10).
           02  ENT1HNML    COMP PIC S9(4).
           02  ENT1HNMF    PIC X.
           02  FILLER REDEFINES ENT1HNMF.
               03  ENT1HNMA    PIC X.
           02  ENT1HNMI    PIC X(20).
           02  ENT1HNOL    COMP PIC S9(4).
           02  ENT1HNOF    PIC X.
           02  FILLER REDEFINES ENT1HNOF.
               03  ENT1HNOA    PIC X.
           02  ENT1HNOI    PIC X(4).
           02  ENT1HPCL    COMP PIC S9(4).
           02  ENT1HPCF    PIC X.
           02  FILLER REDEFINES ENT1HPCF.
               03  ENT1HPCA    PIC X.
           02  ENT1HPCI    PIC X(8).
           02  ENT1HP1L    COMP PIC S9(4).
           02  ENT1HP1F    PIC X.
           02  FILLER REDEFINES ENT1HP1F.
               03  ENT1HP1A    PIC X.
           02  ENT1HP1I    PIC X(20).
           02  ENT1HP2L    COMP PIC S9(4).
           02  ENT1HP2F    PIC X.
           02  FILLER REDEFINES ENT1HP2F.
               03  ENT1HP2A    PIC X.
           02  ENT1HP2I    PIC X(20).
           02  ENT1HMOL    COMP PIC S9(4).
           02  ENT1HMOF    PIC X.
           02  FILLER REDEFINES ENT1HMOF.
               03  ENT1HMOA    PIC X.
           02  ENT1HMOI    PIC X(27).
           02  ENT1OPTL    COMP PIC S9(4).
           02  ENT1OPTF    PIC X.
           02  FILLER REDEFINES ENT1OPTF.
               03  ENT1OPTA    PIC X.
           02  ENT1OPTI    PIC X(1).
           02  ERRFLDL    COMP PIC S9(4).
           02  ERRFLDF    PIC X.
           02  FILLER REDEFINES ERRFLDF.
               03  ERRFLDA    PIC X.
           02  ERRFLDI    PIC X(40).
       01  SSMAPC1O REDEFINES SSMAPC1I.
           02  FILLER PIC X(12).
           02  FILLER PIC X(3).
           02  ENT1CNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENT1FNAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENT1LNAO    PIC X(20).
           02  FILLER PIC X(3).
           02  ENT1DOBO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENT1HNMO    PIC X(20).
           02  FILLER PIC X(3).
           02  ENT1HNOO    PIC X(4).
           02  FILLER PIC X(3).
           02  ENT1HPCO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENT1HP1O    PIC X(20).
           02  FILLER PIC X(3).
           02  ENT1HP2O    PIC X(20).
           02  FILLER PIC X(3).
           02  ENT1HMOO    PIC X(27).
           02  FILLER PIC X(3).
           02  ENT1OPTO    PIC X(1).
           02  FILLER PIC X(3).
           02  ERRFLDO    PIC X(40).
       01  SSMAPP1I.
           02  FILLER PIC X(12).
           02  ENP1PNOL    COMP PIC S9(4).
           02  ENP1PNOF    PIC X.
           02  FILLER REDEFINES ENP1PNOF.
               03  ENP1PNOA    PIC X.
           02  ENP1PNOI    PIC X(10).
           02  ENP1CNOL    COMP PIC S9(4).
           02  ENP1CNOF    PIC X.
           02  FILLER REDEFINES ENP1CNOF.
               03  ENP1CNOA    PIC X.
           02  ENP1CNOI    PIC X(10).
           02  ENP1IDAL    COMP PIC S9(4).
           02  ENP1IDAF    PIC X.
           02  FILLER REDEFINES ENP1IDAF.
               03  ENP1IDAA    PIC X.
           02  ENP1IDAI    PIC X(10).
           02  ENP1EDAL    COMP PIC S9(4).
           02  ENP1EDAF    PIC X.
           02  FILLER REDEFINES ENP1EDAF.
               03  ENP1EDAA    PIC X.
           02  ENP1EDAI    PIC X(10).
           02  ENP1CMKL    COMP PIC S9(4).
           02  ENP1CMKF    PIC X.
           02  FILLER REDEFINES ENP1CMKF.
               03  ENP1CMKA    PIC X.
           02  ENP1CMKI    PIC X(20).
           02  ENP1CMOL    COMP PIC S9(4).
           02  ENP1CMOF    PIC X.
           02  FILLER REDEFINES ENP1CMOF.
               03  ENP1CMOA    PIC X.
           02  ENP1CMOI    PIC X(20).
           02  ENP1VALL    COMP PIC S9(4).
           02  ENP1VALF    PIC X.
           02  FILLER REDEFINES ENP1VALF.
               03  ENP1VALA    PIC X.
           02  ENP1VALI    PIC X(6).
           02  ENP1REGL    COMP PIC S9(4).
           02  ENP1REGF    PIC X.
           02  FILLER REDEFINES ENP1REGF.
               03  ENP1REGA    PIC X.
           02  ENP1REGI    PIC X(7).
           02  ENP1COLL    COMP PIC S9(4).
           02  ENP1COLF    PIC X.
           02  FILLER REDEFINES ENP1COLF.
               03  ENP1COLA    PIC X.
           02  ENP1COLI    PIC X(8).
           02  ENP1CCL    COMP PIC S9(4).
           02  ENP1CCF    PIC X.
           02  FILLER REDEFINES ENP1CCF.
               03  ENP1CCA    PIC X.
           02  ENP1CCI    PIC X(8).
           02  ENP1MANL    COMP PIC S9(4).
           02  ENP1MANF    PIC X.
           02  FILLER REDEFINES ENP1MANF.
               03  ENP1MANA    PIC X.
           02  ENP1MANI    PIC X(10).
           02  ENP1ACCL    COMP PIC S9(4).
           02  ENP1ACCF    PIC X.
           02  FILLER REDEFINES ENP1ACCF.
               03  ENP1ACCA    PIC X.
           02  ENP1ACCI    PIC X(6).
           02  ENP1PREL    COMP PIC S9(4).
           02  ENP1PREF    PIC X.
           02  FILLER REDEFINES ENP1PREF.
               03  ENP1PREA    PIC X.
           02  ENP1PREI    PIC X(6).
           02  ENP1OPTL    COMP PIC S9(4).
           02  ENP1OPTF    PIC X.
           02  FILLER REDEFINES ENP1OPTF.
               03  ENP1OPTA    PIC X.
           02  ENP1OPTI    PIC X(1).
           02  ERP1FLDL    COMP PIC S9(4).
           02  ERP1FLDF    PIC X.
           02  FILLER REDEFINES ERP1FLDF.
               03  ERP1FLDA    PIC X.
           02  ERP1FLDI    PIC X(40).
       01  SSMAPP1O REDEFINES SSMAPP1I.
           02  FILLER PIC X(12).
           02  FILLER PIC X(3).
           02  ENP1PNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP1CNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP1IDAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP1EDAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP1CMKO    PIC X(20).
           02  FILLER PIC X(3).
           02  ENP1CMOO    PIC X(20).
           02  FILLER PIC X(3).
           02  ENP1VALO    PIC X(6).
           02  FILLER PIC X(3).
           02  ENP1REGO    PIC X(7).
           02  FILLER PIC X(3).
           02  ENP1COLO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENP1CCO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENP1MANO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP1ACCO    PIC X(6).
           02  FILLER PIC X(3).
           02  ENP1PREO    PIC X(6).
           02  FILLER PIC X(3).
           02  ENP1OPTO    PIC X(1).
           02  FILLER PIC X(3).
           02  ERP1FLDO    PIC X(40).
       01  SSMAPP2I.
           02  FILLER PIC X(12).
           02  ENP2PNOL    COMP PIC S9(4).
           02  ENP2PNOF    PIC X.
           02  FILLER REDEFINES ENP2PNOF.
               03  ENP2PNOA    PIC X.
           02  ENP2PNOI    PIC X(10).
           02  ENP2CNOL    COMP PIC S9(4).
           02  ENP2CNOF    PIC X.
           02  FILLER REDEFINES ENP2CNOF.
               03  ENP2CNOA    PIC X.
           02  ENP2CNOI    PIC X(10).
           02  ENP2IDAL    COMP PIC S9(4).
           02  ENP2IDAF    PIC X.
           02  FILLER REDEFINES ENP2IDAF.
               03  ENP2IDAA    PIC X.
           02  ENP2IDAI    PIC X(10).
           02  ENP2EDAL    COMP PIC S9(4).
           02  ENP2EDAF    PIC X.
           02  FILLER REDEFINES ENP2EDAF.
               03  ENP2EDAA    PIC X.
           02  ENP2EDAI    PIC X(10).
           02  ENP2FNML    COMP PIC S9(4).
           02  ENP2FNMF    PIC X.
           02  FILLER REDEFINES ENP2FNMF.
               03  ENP2FNMA    PIC X.
           02  ENP2FNMI    PIC X(10).
           02  ENP2TERL    COMP PIC S9(4).
           02  ENP2TERF    PIC X.
           02  FILLER REDEFINES ENP2TERF.
               03  ENP2TERA    PIC X.
           02  ENP2TERI    PIC X(2).
           02  ENP2SUML    COMP PIC S9(4).
           02  ENP2SUMF    PIC X.
           02  FILLER REDEFINES ENP2SUMF.
               03  ENP2SUMA    PIC X.
           02  ENP2SUMI    PIC X(6).
           02  ENP2LIFL    COMP PIC S9(4).
           02  ENP2LIFF    PIC X.
           02  FILLER REDEFINES ENP2LIFF.
               03  ENP2LIFA    PIC X.
           02  ENP2LIFI    PIC X(25).
           02  ENP2WPRL    COMP PIC S9(4).
           02  ENP2WPRF    PIC X.
           02  FILLER REDEFINES ENP2WPRF.
               03  ENP2WPRA    PIC X.
           02  ENP2WPRI    PIC X(1).
           02  ENP2EQUL    COMP PIC S9(4).
           02  ENP2EQUF    PIC X.
           02  FILLER REDEFINES ENP2EQUF.
               03  ENP2EQUA    PIC X.
           02  ENP2EQUI    PIC X(1).
           02  ENP2MANL    COMP PIC S9(4).
           02  ENP2MANF    PIC X.
           02  FILLER REDEFINES ENP2MANF.
               03  ENP2MANA    PIC X.
           02  ENP2MANI    PIC X(1).
           02  ENP2OPTL    COMP PIC S9(4).
           02  ENP2OPTF    PIC X.
           02  FILLER REDEFINES ENP2OPTF.
               03  ENP2OPTA    PIC X.
           02  ENP2OPTI    PIC X(1).
           02  ERP2FLDL    COMP PIC S9(4).
           02  ERP2FLDF    PIC X.
           02  FILLER REDEFINES ERP2FLDF.
               03  ERP2FLDA    PIC X.
           02  ERP2FLDI    PIC X(40).
       01  SSMAPP2O REDEFINES SSMAPP2I.
           02  FILLER PIC X(12).
           02  FILLER PIC X(3).
           02  ENP2PNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP2CNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP2IDAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP2EDAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP2FNMO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP2TERO    PIC X(2).
           02  FILLER PIC X(3).
           02  ENP2SUMO    PIC X(6).
           02  FILLER PIC X(3).
           02  ENP2LIFO    PIC X(25).
           02  FILLER PIC X(3).
           02  ENP2WPRO    PIC X(1).
           02  FILLER PIC X(3).
           02  ENP2EQUO    PIC X(1).
           02  FILLER PIC X(3).
           02  ENP2MANO    PIC X(1).
           02  FILLER PIC X(3).
           02  ENP2OPTO    PIC X(1).
           02  FILLER PIC X(3).
           02  ERP2FLDO    PIC X(40).
       01  SSMAPP3I.
           02  FILLER PIC X(12).
           02  ENP3PNOL    COMP PIC S9(4).
           02  ENP3PNOF    PIC X.
           02  FILLER REDEFINES ENP3PNOF.
               03  ENP3PNOA    PIC X.
           02  ENP3PNOI    PIC X(10).
           02  ENP3CNOL    COMP PIC S9(4).
           02  ENP3CNOF    PIC X.
           02  FILLER REDEFINES ENP3CNOF.
               03  ENP3CNOA    PIC X.
           02  ENP3CNOI    PIC X(10).
           02  ENP3IDAL    COMP PIC S9(4).
           02  ENP3IDAF    PIC X.
           02  FILLER REDEFINES ENP3IDAF.
               03  ENP3IDAA    PIC X.
           02  ENP3IDAI    PIC X(10).
           02  ENP3EDAL    COMP PIC S9(4).
           02  ENP3EDAF    PIC X.
           02  FILLER REDEFINES ENP3EDAF.
               03  ENP3EDAA    PIC X.
           02  ENP3EDAI    PIC X(10).
           02  ENP3TYPL    COMP PIC S9(4).
           02  ENP3TYPF    PIC X.
           02  FILLER REDEFINES ENP3TYPF.
               03  ENP3TYPA    PIC X.
           02  ENP3TYPI    PIC X(15).
           02  ENP3BEDL    COMP PIC S9(4).
           02  ENP3BEDF    PIC X.
           02  FILLER REDEFINES ENP3BEDF.
               03  ENP3BEDA    PIC X.
           02  ENP3BEDI    PIC X(3).
           02  ENP3VALL    COMP PIC S9(4).
           02  ENP3VALF    PIC X.
           02  FILLER REDEFINES ENP3VALF.
               03  ENP3VALA    PIC X.
           02  ENP3VALI    PIC X(8).
           02  ENP3HNML    COMP PIC S9(4).
           02  ENP3HNMF    PIC X.
           02  FILLER REDEFINES ENP3HNMF.
               03  ENP3HNMA    PIC X.
           02  ENP3HNMI    PIC X(20).
           02  ENP3HNOL    COMP PIC S9(4).
           02  ENP3HNOF    PIC X.
           02  FILLER REDEFINES ENP3HNOF.
               03  ENP3HNOA    PIC X.
           02  ENP3HNOI    PIC X(4).
           02  ENP3HPCL    COMP PIC S9(4).
           02  ENP3HPCF    PIC X.
           02  FILLER REDEFINES ENP3HPCF.
               03  ENP3HPCA    PIC X.
           02  ENP3HPCI    PIC X(8).
           02  ENP3OPTL    COMP PIC S9(4).
           02  ENP3OPTF    PIC X.
           02  FILLER REDEFINES ENP3OPTF.
               03  ENP3OPTA    PIC X.
           02  ENP3OPTI    PIC X(1).
           02  ERP3FLDL    COMP PIC S9(4).
           02  ERP3FLDF    PIC X.
           02  FILLER REDEFINES ERP3FLDF.
               03  ERP3FLDA    PIC X.
           02  ERP3FLDI    PIC X(40).
       01  SSMAPP3O REDEFINES SSMAPP3I.
           02  FILLER PIC X(12).
           02  FILLER PIC X(3).
           02  ENP3PNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP3CNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP3IDAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP3EDAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP3TYPO    PIC X(15).
           02  FILLER PIC X(3).
           02  ENP3BEDO    PIC X(3).
           02  FILLER PIC X(3).
           02  ENP3VALO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENP3HNMO    PIC X(20).
           02  FILLER PIC X(3).
           02  ENP3HNOO    PIC X(4).
           02  FILLER PIC X(3).
           02  ENP3HPCO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENP3OPTO    PIC X(1).
           02  FILLER PIC X(3).
           02  ERP3FLDO    PIC X(40).
       01  SSMAPP4I.
           02  FILLER PIC X(12).
           02  ENP4PNOL    COMP PIC S9(4).
           02  ENP4PNOF    PIC X.
           02  FILLER REDEFINES ENP4PNOF.
               03  ENP4PNOA    PIC X.
           02  ENP4PNOI    PIC X(10).
           02  ENP4CNOL    COMP PIC S9(4).
           02  ENP4CNOF    PIC X.
           02  FILLER REDEFINES ENP4CNOF.
               03  ENP4CNOA    PIC X.
           02  ENP4CNOI    PIC X(10).
           02  ENP4IDAL    COMP PIC S9(4).
           02  ENP4IDAF    PIC X.
           02  FILLER REDEFINES ENP4IDAF.
               03  ENP4IDAA    PIC X.
           02  ENP4IDAI    PIC X(10).
           02  ENP4EDAL    COMP PIC S9(4).
           02  ENP4EDAF    PIC X.
           02  FILLER REDEFINES ENP4EDAF.
               03  ENP4EDAA    PIC X.
           02  ENP4EDAI    PIC X(10).
           02  ENP4ADDL    COMP PIC S9(4).
           02  ENP4ADDF    PIC X.
           02  FILLER REDEFINES ENP4ADDF.
               03  ENP4ADDA    PIC X.
           02  ENP4ADDI    PIC X(25).
           02  ENP4HPCL    COMP PIC S9(4).
           02  ENP4HPCF    PIC X.
           02  FILLER REDEFINES ENP4HPCF.
               03  ENP4HPCA    PIC X.
           02  ENP4HPCI    PIC X(8).
           02  ENP4LATL    COMP PIC S9(4).
           02  ENP4LATF    PIC X.
           02  FILLER REDEFINES ENP4LATF.
               03  ENP4LATA    PIC X.
           02  ENP4LATI    PIC X(11).
           02  ENP4LONL    COMP PIC S9(4).
           02  ENP4LONF    PIC X.
           02  FILLER REDEFINES ENP4LONF.
               03  ENP4LONA    PIC X.
           02  ENP4LONI    PIC X(11).
           02  ENP4CUSL    COMP PIC S9(4).
           02  ENP4CUSF    PIC X.
           02  FILLER REDEFINES ENP4CUSF.
               03  ENP4CUSA    PIC X.
           02  ENP4CUSI    PIC X(25).
           02  ENP4PTYL    COMP PIC S9(4).
           02  ENP4PTYF    PIC X.
           02  FILLER REDEFINES ENP4PTYF.
               03  ENP4PTYA    PIC X.
           02  ENP4PTYI    PIC X(25).
           02  ENP4FPEL    COMP PIC S9(4).
           02  ENP4FPEF    PIC X.
           02  FILLER REDEFINES ENP4FPEF.
               03  ENP4FPEA    PIC X.
           02  ENP4FPEI    PIC X(4).
           02  ENP4FPRL    COMP PIC S9(4).
           02  ENP4FPRF    PIC X.
           02  FILLER REDEFINES ENP4FPRF.
               03  ENP4FPRA    PIC X.
           02  ENP4FPRI    PIC X(8).
           02  ENP4CPEL    COMP PIC S9(4).
           02  ENP4CPEF    PIC X.
           02  FILLER REDEFINES ENP4CPEF.
               03  ENP4CPEA    PIC X.
           02  ENP4CPEI    PIC X(4).
           02  ENP4CPRL    COMP PIC S9(4).
           02  ENP4CPRF    PIC X.
           02  FILLER REDEFINES ENP4CPRF.
               03  ENP4CPRA    PIC X.
           02  ENP4CPRI    PIC X(8).
           02  ENP4XPEL    COMP PIC S9(4).
           02  ENP4XPEF    PIC X.
           02  FILLER REDEFINES ENP4XPEF.
               03  ENP4XPEA    PIC X.
           02  ENP4XPEI    PIC X(4).
           02  ENP4XPRL    COMP PIC S9(4).
           02  ENP4XPRF    PIC X.
           02  FILLER REDEFINES ENP4XPRF.
               03  ENP4XPRA    PIC X.
           02  ENP4XPRI    PIC X(8).
           02  ENP4WPEL    COMP PIC S9(4).
           02  ENP4WPEF    PIC X.
           02  FILLER REDEFINES ENP4WPEF.
               03  ENP4WPEA    PIC X.
           02  ENP4WPEI    PIC X(4).
           02  ENP4WPRL    COMP PIC S9(4).
           02  ENP4WPRF    PIC X.
           02  FILLER REDEFINES ENP4WPRF.
               03  ENP4WPRA    PIC X.
           02  ENP4WPRI    PIC X(8).
           02  ENP4STAL    COMP PIC S9(4).
           02  ENP4STAF    PIC X.
           02  FILLER REDEFINES ENP4STAF.
               03  ENP4STAA    PIC X.
           02  ENP4STAI    PIC X(4).
           02  ENP4REJL    COMP PIC S9(4).
           02  ENP4REJF    PIC X.
           02  FILLER REDEFINES ENP4REJF.
               03  ENP4REJA    PIC X.
           02  ENP4REJI    PIC X(25).
           02  ENP4OPTL    COMP PIC S9(4).
           02  ENP4OPTF    PIC X.
           02  FILLER REDEFINES ENP4OPTF.
               03  ENP4OPTA    PIC X.
           02  ENP4OPTI    PIC X(1).
           02  ERP4FLDL    COMP PIC S9(4).
           02  ERP4FLDF    PIC X.
           02  FILLER REDEFINES ERP4FLDF.
               03  ERP4FLDA    PIC X.
           02  ERP4FLDI    PIC X(40).
       01  SSMAPP4O REDEFINES SSMAPP4I.
           02  FILLER PIC X(12).
           02  FILLER PIC X(3).
           02  ENP4PNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP4CNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP4IDAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP4EDAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP4ADDO    PIC X(25).
           02  FILLER PIC X(3).
           02  ENP4HPCO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENP4LATO    PIC X(11).
           02  FILLER PIC X(3).
           02  ENP4LONO    PIC X(11).
           02  FILLER PIC X(3).
           02  ENP4CUSO    PIC X(25).
           02  FILLER PIC X(3).
           02  ENP4PTYO    PIC X(25).
           02  FILLER PIC X(3).
           02  ENP4FPEO    PIC X(4).
           02  FILLER PIC X(3).
           02  ENP4FPRO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENP4CPEO    PIC X(4).
           02  FILLER PIC X(3).
           02  ENP4CPRO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENP4XPEO    PIC X(4).
           02  FILLER PIC X(3).
           02  ENP4XPRO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENP4WPEO    PIC X(4).
           02  FILLER PIC X(3).
           02  ENP4WPRO    PIC X(8).
           02  FILLER PIC X(3).
           02  ENP4STAO    PIC X(4).
           02  FILLER PIC X(3).
           02  ENP4REJO    PIC X(25).
           02  FILLER PIC X(3).
           02  ENP4OPTO    PIC X(1).
           02  FILLER PIC X(3).
           02  ERP4FLDO    PIC X(40).
       01  SSMAPP5I.
           02  FILLER PIC X(12).
           02  ENP5LNOL    COMP PIC S9(4).
           02  ENP5LNOF    PIC X.
           02  FILLER REDEFINES ENP5LNOF.
               03  ENP5LNOA    PIC X.
           02  ENP5LNOI    PIC X(10).
           02  ENP5PNOL    COMP PIC S9(4).
           02  ENP5PNOF    PIC X.
           02  FILLER REDEFINES ENP5PNOF.
               03  ENP5PNOA    PIC X.
           02  ENP5PNOI    PIC X(10).
           02  ENP5CNOL    COMP PIC S9(4).
           02  ENP5CNOF    PIC X.
           02  FILLER REDEFINES ENP5CNOF.
               03  ENP5CNOA    PIC X.
           02  ENP5CNOI    PIC X(10).
           02  ENP5CDAL    COMP PIC S9(4).
           02  ENP5CDAF    PIC X.
           02  FILLER REDEFINES ENP5CDAF.
               03  ENP5CDAA    PIC X.
           02  ENP5CDAI    PIC X(10).
           02  ENP5PADL    COMP PIC S9(4).
           02  ENP5PADF    PIC X.
           02  FILLER REDEFINES ENP5PADF.
               03  ENP5PADA    PIC X.
           02  ENP5PADI    PIC X(10).
           02  ENP5VALL    COMP PIC S9(4).
           02  ENP5VALF    PIC X.
           02  FILLER REDEFINES ENP5VALF.
               03  ENP5VALA    PIC X.
           02  ENP5VALI    PIC X(10).
           02  ENP5CAUL    COMP PIC S9(4).
           02  ENP5CAUF    PIC X.
           02  FILLER REDEFINES ENP5CAUF.
               03  ENP5CAUA    PIC X.
           02  ENP5CAUI    PIC X(25).
           02  ENP5OBSL    COMP PIC S9(4).
           02  ENP5OBSF    PIC X.
           02  FILLER REDEFINES ENP5OBSF.
               03  ENP5OBSA    PIC X.
           02  ENP5OBSI    PIC X(25).
           02  ENP5OPTL    COMP PIC S9(4).
           02  ENP5OPTF    PIC X.
           02  FILLER REDEFINES ENP5OPTF.
               03  ENP5OPTA    PIC X.
           02  ENP5OPTI    PIC X(1).
           02  ERP5FLDL    COMP PIC S9(4).
           02  ERP5FLDF    PIC X.
           02  FILLER REDEFINES ERP5FLDF.
               03  ERP5FLDA    PIC X.
           02  ERP5FLDI    PIC X(40).
       01  SSMAPP5O REDEFINES SSMAPP5I.
           02  FILLER PIC X(12).
           02  FILLER PIC X(3).
           02  ENP5LNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP5PNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP5CNOO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP5CDAO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP5PADO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP5VALO    PIC X(10).
           02  FILLER PIC X(3).
           02  ENP5CAUO    PIC X(25).
           02  FILLER PIC X(3).
           02  ENP5OBSO    PIC X(25).
           02  FILLER PIC X(3).
           02  ENP5OPTO    PIC X(1).
           02  FILLER PIC X(3).
           02  ERP5FLDO    PIC X(40).
      * <<< END COPY SSMAP
       01 COMM-AREA.
      * >>> BEGIN COPY LGCMAREA (LGCMAREA.cpy)
      ******************************************************************
      *                                                                *
      * (C) Copyright IBM Corp. 2011, 2020                             *
      *                                                                *
      *               COPYBOOK for COMMAREA structure                  *
      *                                                                *
      *   This commarea can be used for all functions                  *
      *                                                                *
      ******************************************************************
           03 CA-REQUEST-ID            PIC X(6).
           03 CA-RETURN-CODE           PIC 9(2).
           03 CA-CUSTOMER-NUM          PIC 9(10).
           03 CA-REQUEST-SPECIFIC      PIC X(32482).
      *    Fields used in INQ All and ADD customer
           03 CA-CUSTOMER-REQUEST REDEFINES CA-REQUEST-SPECIFIC.
              05 CA-FIRST-NAME         PIC X(10).
              05 CA-LAST-NAME          PIC X(20).
              05 CA-DOB                PIC X(10).
              05 CA-HOUSE-NAME         PIC X(20).
              05 CA-HOUSE-NUM          PIC X(4).
              05 CA-POSTCODE           PIC X(8).
              05 CA-NUM-POLICIES       PIC 9(3).
              05 CA-PHONE-MOBILE       PIC X(20).
              05 CA-PHONE-HOME         PIC X(20).
              05 CA-EMAIL-ADDRESS      PIC X(100).
              05 CA-POLICY-DATA        PIC X(32267).
      *    Fields used in Customer security call
           03 CA-CUSTSECR-REQUEST REDEFINES CA-REQUEST-SPECIFIC.
              05 CA-CUSTSECR-PASS      PIC X(32).
              05 CA-CUSTSECR-COUNT     PIC X(4).
              05 CA-CUSTSECR-STATE     PIC X.
              05 CA-CUSTSECR-DATA      PIC X(32445).
      *    Fields used in INQ, UPD, ADD & DELETE policy
           03 CA-POLICY-REQUEST REDEFINES CA-REQUEST-SPECIFIC.
              05 CA-POLICY-NUM         PIC 9(10).
      *       Common policy details
              05 CA-POLICY-COMMON.
                 07 CA-ISSUE-DATE      PIC X(10).
                 07 CA-EXPIRY-DATE     PIC X(10).
                 07 CA-LASTCHANGED     PIC X(26).
                 07 CA-BROKERID        PIC 9(10).
                 07 CA-BROKERSREF      PIC X(10).
                 07 CA-PAYMENT         PIC 9(6).
              05 CA-POLICY-SPECIFIC    PIC X(32400).
      *       Endowment policy description
              05 CA-ENDOWMENT REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-E-WITH-PROFITS    PIC X.
                 07 CA-E-EQUITIES        PIC X.
                 07 CA-E-MANAGED-FUND    PIC X.
                 07 CA-E-FUND-NAME       PIC X(10).
                 07 CA-E-TERM            PIC 99.
                 07 CA-E-SUM-ASSURED     PIC 9(6).
                 07 CA-E-LIFE-ASSURED    PIC X(31).
                 07 CA-E-PADDING-DATA    PIC X(32348).
      *       House policy description
              05 CA-HOUSE REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-H-PROPERTY-TYPE   PIC X(15).
                 07 CA-H-BEDROOMS        PIC 9(3).
                 07 CA-H-VALUE           PIC 9(8).
                 07 CA-H-HOUSE-NAME      PIC X(20).
                 07 CA-H-HOUSE-NUMBER    PIC X(4).
                 07 CA-H-POSTCODE        PIC X(8).
                 07 CA-H-FILLER          PIC X(32342).
      *       Motor policy description
              05 CA-MOTOR REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-M-MAKE            PIC X(15).
                 07 CA-M-MODEL           PIC X(15).
                 07 CA-M-VALUE           PIC 9(6).
                 07 CA-M-REGNUMBER       PIC X(7).
                 07 CA-M-COLOUR          PIC X(8).
                 07 CA-M-CC              PIC 9(4).
                 07 CA-M-MANUFACTURED    PIC X(10).
                 07 CA-M-PREMIUM         PIC 9(6).
                 07 CA-M-ACCIDENTS       PIC 9(6).
                 07 CA-M-FILLER          PIC X(32323).
      *       Commercial policy description
              05 CA-COMMERCIAL REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-B-Address         PIC X(255).
                 07 CA-B-Postcode        PIC X(8).
                 07 CA-B-Latitude        PIC X(11).
                 07 CA-B-Longitude       PIC X(11).
                 07 CA-B-Customer        PIC X(255).
                 07 CA-B-PropType        PIC X(255).
                 07 CA-B-FirePeril       PIC 9(4).
                 07 CA-B-FirePremium     PIC 9(8).
                 07 CA-B-CrimePeril      PIC 9(4).
                 07 CA-B-CrimePremium    PIC 9(8).
                 07 CA-B-FloodPeril      PIC 9(4).
                 07 CA-B-FloodPremium    PIC 9(8).
                 07 CA-B-WeatherPeril    PIC 9(4).
                 07 CA-B-WeatherPremium  PIC 9(8).
                 07 CA-B-Status          PIC 9(4).
                 07 CA-B-RejectReason    PIC X(255).
                 07 CA-B-FILLER          PIC X(31298).
      *       CLAIM policy description
              05 CA-CLAIM      REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-C-Num             PIC 9(10).
                 07 CA-C-Date            PIC X(10).
                 07 CA-C-Paid            PIC 9(8).
                 07 CA-C-Value           PIC 9(8).
                 07 CA-C-Cause           PIC X(255).
                 07 CA-C-Observations    PIC X(255).
                 07 CA-C-FILLER          PIC X(31854).
      * <<< END COPY LGCMAREA

      *----------------------------------------------------------------*
      *****************************************************************
      * >>> TOOL-GENERATED MOCK SUPPORT FIELDS <<<
       01  EIBCALEN     PIC S9(4) COMP VALUE 9999.
       PROCEDURE DIVISION.

      *---------------------------------------------------------------*
       MAINLINE SECTION.

           IF EIBCALEN > 0
              GO TO A-GAIN.

           Initialize SSMAPP2I.
           Initialize SSMAPP2O.
           Initialize COMM-AREA.
           MOVE '0000000000'   To ENP2CNOO.
           MOVE '0000000000'   To ENP2PNOO.

      * Display Main Menu
      *    EXEC CICS SEND MAP ('SSMAPP2')
      *              MAPSET ('SSMAP')
      *              ERASE
      *              END-EXEC.
           DISPLAY '>>> MOCK SEND MAP @MAINLINE: ' 'SSMAPP2'.

       A-GAIN.

      *    EXEC CICS HANDLE AID
      *              CLEAR(CLEARIT)
      *              PF3(ENDIT) END-EXEC.
           DISPLAY '>>> MOCK HANDLE AID @A-GAIN'.
      *    EXEC CICS HANDLE CONDITION
      *              MAPFAIL(ENDIT)
      *              END-EXEC.
           DISPLAY '>>> MOCK HANDLE CONDITION @A-GAIN'.

      *    EXEC CICS RECEIVE MAP('SSMAPP2')
      *              INTO(SSMAPP2I)
      *              MAPSET('SSMAP') END-EXEC.
           DISPLAY '>>> MOCK RECEIVE MAP @A-GAIN: ' 'SSMAPP2'
           MOVE 0 TO ENP2PNOL
           MOVE ' ' TO ENP2PNOF
           MOVE 'DUMMY' TO ENP2PNOI
           MOVE 0 TO ENP2CNOL
           MOVE ' ' TO ENP2CNOF
           MOVE 'DUMMY' TO ENP2CNOI
           MOVE 0 TO ENP2IDAL
           MOVE ' ' TO ENP2IDAF
           MOVE 'DUMMY' TO ENP2IDAI
           MOVE 0 TO ENP2EDAL
           MOVE ' ' TO ENP2EDAF
           MOVE 'DUMMY' TO ENP2EDAI
           MOVE 0 TO ENP2FNML
           MOVE ' ' TO ENP2FNMF
           MOVE 'DUMMY' TO ENP2FNMI
           MOVE 0 TO ENP2TERL
           MOVE ' ' TO ENP2TERF
           MOVE 'DU' TO ENP2TERI
           MOVE 0 TO ENP2SUML
           MOVE ' ' TO ENP2SUMF
           MOVE 'DUMMY' TO ENP2SUMI
           MOVE 0 TO ENP2LIFL
           MOVE ' ' TO ENP2LIFF
           MOVE 'DUMMY' TO ENP2LIFI
           MOVE 0 TO ENP2WPRL
           MOVE ' ' TO ENP2WPRF
           MOVE ' ' TO ENP2WPRI
           MOVE 0 TO ENP2EQUL
           MOVE ' ' TO ENP2EQUF
           MOVE ' ' TO ENP2EQUI
           MOVE 0 TO ENP2MANL
           MOVE ' ' TO ENP2MANF
           MOVE ' ' TO ENP2MANI
           MOVE 0 TO ENP2OPTL
           MOVE ' ' TO ENP2OPTF
           MOVE ' ' TO ENP2OPTI
           MOVE 0 TO ERP2FLDL
           MOVE ' ' TO ERP2FLDF
           MOVE 'DUMMY' TO ERP2FLDI.


           EVALUATE ENP2OPTO

             WHEN '1'
                 Move '01IEND'   To CA-REQUEST-ID
                 Move ENP2CNOO   To CA-CUSTOMER-NUM
                 Move ENP2PNOO   To CA-POLICY-NUM
      *          EXEC CICS LINK PROGRAM('LGIPOL01')
      *                    COMMAREA(COMM-AREA)
      *                    LENGTH(32500)
      *          END-EXEC
                 DISPLAY '>>> MOCK LINK @A-GAIN: ' 'LGIPOL01'
                 IF CA-RETURN-CODE > 0
                   GO TO NO-DATA
                 END-IF

                 Move CA-ISSUE-DATE     To  ENP2IDAI
                 Move CA-EXPIRY-DATE    To  ENP2EDAI
                 Move CA-E-FUND-NAME    To  ENP2FNMI
                 Move CA-E-TERM         To  ENP2TERI
                 Move CA-E-SUM-ASSURED  To  ENP2SUMI
                 Move CA-E-LIFE-ASSURED To  ENP2LIFI
                 Move CA-E-WITH-PROFITS To  ENP2WPRI
                 Move CA-E-MANAGED-FUND To  ENP2MANI
                 Move CA-E-EQUITIES     To  ENP2EQUI
      *          EXEC CICS SEND MAP ('SSMAPP2')
      *                    FROM(SSMAPP2O)
      *                    MAPSET ('SSMAP')
      *          END-EXEC
                 DISPLAY '>>> MOCK SEND MAP @A-GAIN: ' 'SSMAPP2'
                 DISPLAY '    DATA: ' SSMAPP2O
                 GO TO ENDIT-STARTIT

             WHEN '2'
                 Move '01AEND'          To CA-REQUEST-ID
                 Move ENP2CNOI          To CA-CUSTOMER-NUM
                 Move 0                 To CA-PAYMENT
                 Move 0                 To CA-BROKERID
                 Move '        '        To CA-BROKERSREF
                 Move ENP2IDAI          To CA-ISSUE-DATE
                 Move ENP2EDAI          To CA-EXPIRY-DATE
                 Move ENP2FNMI          To CA-E-FUND-NAME
                 Move ENP2TERI          To CA-E-TERM
                 Move ENP2SUMI          To CA-E-SUM-ASSURED
                 Move ENP2LIFI          To CA-E-LIFE-ASSURED
                 Move ENP2WPRI          To CA-E-WITH-PROFITS
                 Move ENP2MANI          To CA-E-MANAGED-FUND
                 Move ENP2EQUI          To CA-E-EQUITIES
      *          EXEC CICS LINK PROGRAM('LGAPOL01')
      *                    COMMAREA(COMM-AREA)
      *                    LENGTH(32500)
      *          END-EXEC
                 DISPLAY '>>> MOCK LINK @A-GAIN: ' 'LGAPOL01'
                 IF CA-RETURN-CODE > 0
      *            Exec CICS Syncpoint Rollback End-Exec
                   DISPLAY '>>> MOCK SYNCPOINT @A-GAIN'
                   GO TO NO-ADD
                 END-IF
                 Move CA-CUSTOMER-NUM To ENP2CNOI
                 Move CA-POLICY-NUM   To ENP2PNOI
                 Move CA-E-FUND-NAME  To ENP2FNMI
                 Move ' '             To ENP2OPTI
                 Move 'New Life Policy Inserted'
                   To  ERP2FLDO
      *          EXEC CICS SEND MAP ('SSMAPP2')
      *                    FROM(SSMAPP2O)
      *                    MAPSET ('SSMAP')
      *          END-EXEC
                 DISPLAY '>>> MOCK SEND MAP @A-GAIN: ' 'SSMAPP2'
                 DISPLAY '    DATA: ' SSMAPP2O
                 GO TO ENDIT-STARTIT

             WHEN '3'
                 Move '01DEND'   To CA-REQUEST-ID
                 Move ENP2CNOO   To CA-CUSTOMER-NUM
                 Move ENP2PNOO   To CA-POLICY-NUM
      *          EXEC CICS LINK PROGRAM('LGDPOL01')
      *                    COMMAREA(COMM-AREA)
      *                    LENGTH(32500)
      *          END-EXEC
                 DISPLAY '>>> MOCK LINK @A-GAIN: ' 'LGDPOL01'
                 IF CA-RETURN-CODE > 0
      *            Exec CICS Syncpoint Rollback End-Exec
                   DISPLAY '>>> MOCK SYNCPOINT @A-GAIN'
                   GO TO NO-DELETE
                 END-IF

                 Move Spaces            To  ENP2IDAI
                 Move Spaces            To  ENP2EDAI
                 Move Spaces            To  ENP2FNMI
                 Move Spaces            To  ENP2TERI
                 Move Spaces            To  ENP2SUMI
                 Move Spaces            To  ENP2LIFI
                 Move Spaces            To  ENP2WPRI
                 Move Spaces            To  ENP2MANI
                 Move Spaces            To  ENP2EQUI
                 Move 'Life Policy Deleted'
                   To  ERP2FLDO
      *          EXEC CICS SEND MAP ('SSMAPP2')
      *                    FROM(SSMAPP2O)
      *                    MAPSET ('SSMAP')
      *          END-EXEC
                 DISPLAY '>>> MOCK SEND MAP @A-GAIN: ' 'SSMAPP2'
                 DISPLAY '    DATA: ' SSMAPP2O
                 GO TO ENDIT-STARTIT

             WHEN '4'
                 Move '01IEND'   To CA-REQUEST-ID
                 Move ENP2CNOO   To CA-CUSTOMER-NUM
                 Move ENP2PNOO   To CA-POLICY-NUM
      *          EXEC CICS LINK PROGRAM('LGIPOL01')
      *                    COMMAREA(COMM-AREA)
      *                    LENGTH(32500)
      *          END-EXEC
                 DISPLAY '>>> MOCK LINK @A-GAIN: ' 'LGIPOL01'
                 IF CA-RETURN-CODE > 0
                   GO TO NO-DATA
                 END-IF

                 Move CA-ISSUE-DATE     To  ENP2IDAI
                 Move CA-EXPIRY-DATE    To  ENP2EDAI
                 Move CA-E-FUND-NAME    To  ENP2FNMI
                 Move CA-E-TERM         To  ENP2TERI
                 Move CA-E-SUM-ASSURED  To  ENP2SUMI
                 Move CA-E-LIFE-ASSURED To  ENP2LIFI
                 Move CA-E-WITH-PROFITS To  ENP2WPRI
                 Move CA-E-MANAGED-FUND To  ENP2MANI
                 Move CA-E-EQUITIES     To  ENP2EQUI
      *          EXEC CICS SEND MAP ('SSMAPP2')
      *                    FROM(SSMAPP2O)
      *                    MAPSET ('SSMAP')
      *          END-EXEC
                 DISPLAY '>>> MOCK SEND MAP @A-GAIN: ' 'SSMAPP2'
                 DISPLAY '    DATA: ' SSMAPP2O
      *          EXEC CICS RECEIVE MAP('SSMAPP2')
      *                    INTO(SSMAPP2I)
      *                    MAPSET('SSMAP') END-EXEC
                 DISPLAY '>>> MOCK RECEIVE MAP @A-GAIN: ' 'SSMAPP2'
                 MOVE 0 TO ENP2PNOL
                 MOVE ' ' TO ENP2PNOF
                 MOVE 'DUMMY' TO ENP2PNOI
                 MOVE 0 TO ENP2CNOL
                 MOVE ' ' TO ENP2CNOF
                 MOVE 'DUMMY' TO ENP2CNOI
                 MOVE 0 TO ENP2IDAL
                 MOVE ' ' TO ENP2IDAF
                 MOVE 'DUMMY' TO ENP2IDAI
                 MOVE 0 TO ENP2EDAL
                 MOVE ' ' TO ENP2EDAF
                 MOVE 'DUMMY' TO ENP2EDAI
                 MOVE 0 TO ENP2FNML
                 MOVE ' ' TO ENP2FNMF
                 MOVE 'DUMMY' TO ENP2FNMI
                 MOVE 0 TO ENP2TERL
                 MOVE ' ' TO ENP2TERF
                 MOVE 'DU' TO ENP2TERI
                 MOVE 0 TO ENP2SUML
                 MOVE ' ' TO ENP2SUMF
                 MOVE 'DUMMY' TO ENP2SUMI
                 MOVE 0 TO ENP2LIFL
                 MOVE ' ' TO ENP2LIFF
                 MOVE 'DUMMY' TO ENP2LIFI
                 MOVE 0 TO ENP2WPRL
                 MOVE ' ' TO ENP2WPRF
                 MOVE ' ' TO ENP2WPRI
                 MOVE 0 TO ENP2EQUL
                 MOVE ' ' TO ENP2EQUF
                 MOVE ' ' TO ENP2EQUI
                 MOVE 0 TO ENP2MANL
                 MOVE ' ' TO ENP2MANF
                 MOVE ' ' TO ENP2MANI
                 MOVE 0 TO ENP2OPTL
                 MOVE ' ' TO ENP2OPTF
                 MOVE ' ' TO ENP2OPTI
                 MOVE 0 TO ERP2FLDL
                 MOVE ' ' TO ERP2FLDF
                 MOVE 'DUMMY' TO ERP2FLDI

                 Move '01UEND'          To CA-REQUEST-ID
                 Move ENP2CNOI          To CA-CUSTOMER-NUM
                 Move 0                 To CA-PAYMENT
                 Move 0                 To CA-BROKERID
                 Move '        '        To CA-BROKERSREF
                 Move ENP2IDAI          To CA-ISSUE-DATE
                 Move ENP2EDAI          To CA-EXPIRY-DATE
                 Move ENP2FNMI          To CA-E-FUND-NAME
                 Move ENP2TERI          To CA-E-TERM
                 Move ENP2SUMI          To CA-E-SUM-ASSURED
                 Move ENP2LIFI          To CA-E-LIFE-ASSURED
                 Move ENP2WPRI          To CA-E-WITH-PROFITS
                 Move ENP2MANI          To CA-E-MANAGED-FUND
                 Move ENP2EQUI          To CA-E-EQUITIES
      *          EXEC CICS LINK PROGRAM('LGUPOL01')
      *                    COMMAREA(COMM-AREA)
      *                    LENGTH(32500)
      *          END-EXEC
                 DISPLAY '>>> MOCK LINK @A-GAIN: ' 'LGUPOL01'
                 IF CA-RETURN-CODE > 0
                   GO TO NO-UPD
                 END-IF

                 Move CA-CUSTOMER-NUM To ENP2CNOI
                 Move CA-POLICY-NUM   To ENP2PNOI
                 Move ' '             To ENP2OPTI
                 Move 'Life Policy Updated'
                   To  ERP2FLDO
      *          EXEC CICS SEND MAP ('SSMAPP2')
      *                    FROM(SSMAPP2O)
      *                    MAPSET ('SSMAP')
      *          END-EXEC
                 DISPLAY '>>> MOCK SEND MAP @A-GAIN: ' 'SSMAPP2'
                 DISPLAY '    DATA: ' SSMAPP2O

                 GO TO ENDIT-STARTIT

             WHEN OTHER

                 Move 'Please enter a valid option'
                   To  ERP2FLDO
                 Move -1 To ENP2OPTL

      *          EXEC CICS SEND MAP ('SSMAPP2')
      *                    FROM(SSMAPP2O)
      *                    MAPSET ('SSMAP')
      *                    CURSOR
      *          END-EXEC
                 DISPLAY '>>> MOCK SEND MAP @A-GAIN: ' 'SSMAPP2'
                 DISPLAY '    DATA: ' SSMAPP2O
                 GO TO ENDIT-STARTIT

           END-EVALUATE.


      *    Send message to terminal and return

      *    EXEC CICS RETURN
      *    END-EXEC.
           DISPLAY '>>> MOCK RETURN @A-GAIN'
           GOBACK.

       ENDIT-STARTIT.
      *    EXEC CICS RETURN
      *         TRANSID('SSP2')
      *         COMMAREA(COMM-AREA)
      *         END-EXEC.
           DISPLAY '>>> MOCK RETURN @ENDIT-STARTIT: ' 'SSP2'
           GOBACK.

       ENDIT.
      *    EXEC CICS SEND TEXT
      *              FROM(MSGEND)
      *              LENGTH(LENGTH OF MSGEND)
      *              ERASE
      *              FREEKB
      *    END-EXEC
           DISPLAY '>>> MOCK SEND TEXT @ENDIT'
           DISPLAY '    DATA: ' MSGEND
      *    EXEC CICS RETURN
      *    END-EXEC.
           DISPLAY '>>> MOCK RETURN @ENDIT'
           GOBACK.

       CLEARIT.

           Initialize SSMAPP2I.
      *    EXEC CICS SEND MAP ('SSMAPP2')
      *              MAPSET ('SSMAP')
      *              MAPONLY
      *    END-EXEC
           DISPLAY '>>> MOCK SEND MAP @CLEARIT: ' 'SSMAPP2'

      *    EXEC CICS RETURN
      *         TRANSID('SSP2')
      *         COMMAREA(COMM-AREA)
      *         END-EXEC.
           DISPLAY '>>> MOCK RETURN @CLEARIT: ' 'SSP2'
           GOBACK.

       NO-ADD.
           Evaluate CA-RETURN-CODE
             When 70
               Move 'Customer does not exist'          To  ERP1FLDO
               Go To ERROR-OUT
             When Other
               Move 'Error Adding Life Policy'        To  ERP1FLDO
               Go To ERROR-OUT
           End-Evaluate.

       NO-UPD.
           Move 'Error Updating Life Policy'       To  ERP2FLDO
           Go To ERROR-OUT.

       NO-DELETE.
           Move 'Error Deleting Life Policy'       To  ERP2FLDO
           Go To ERROR-OUT.

       NO-DATA.
           Move 'No data was returned.'            To  ERP2FLDO
           Go To ERROR-OUT.

       ERROR-OUT.
      *    EXEC CICS SEND MAP ('SSMAPP2')
      *              FROM(SSMAPP2O)
      *              MAPSET ('SSMAP')
      *    END-EXEC.
           DISPLAY '>>> MOCK SEND MAP @ERROR-OUT: ' 'SSMAPP2'
           DISPLAY '    DATA: ' SSMAPP2O.

           Initialize SSMAPP2I.
           Initialize SSMAPP2O.
           Initialize COMM-AREA.

           GO TO ENDIT-STARTIT.
