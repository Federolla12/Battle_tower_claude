/*
 * Gen 3 Battle Engine - Fast Rollout Simulator (C Extension)
 * Data-driven: move data passed from Python at init time via init_moves_data().
 *
 * Compile (single-threaded):
 *   Linux:   gcc -O3 -shared -fPIC -o gen3/rollout.so gen3/rollout.c -lm
 *   Windows: gcc -O3 -shared -o gen3/rollout.dll gen3/rollout.c
 *
 * Compile (OpenMP — recommended, uses all CPU cores):
 *   Linux:   gcc -O3 -shared -fPIC -fopenmp -o gen3/rollout.so gen3/rollout.c -lm
 *   Windows: gcc -O3 -shared -fopenmp -o gen3/rollout.dll gen3/rollout.c
 */
#include <stdlib.h>
#include <string.h>
#ifdef _OPENMP
#include <omp.h>
#endif

#ifdef _WIN32
  #define EXPORT __declspec(dllexport)
#else
  #define EXPORT __attribute__((visibility("default")))
#endif

/* ── Types ──────────────────────────────────────────────────────── */
enum Type{T_NORMAL,T_FIGHTING,T_FLYING,T_POISON,T_GROUND,T_ROCK,T_BUG,T_GHOST,
          T_STEEL,T_FIRE,T_WATER,T_GRASS,T_ELECTRIC,T_PSYCHIC,T_ICE,T_DRAGON,
          T_DARK,T_NONE,T_UNK,NUM_T};
#define PHYS(t) ((t)<=T_STEEL)

/* ── Status ─────────────────────────────────────────────────────── */
enum{ST_NONE,ST_BURN,ST_PARA,ST_POISON,ST_TOXIC,ST_FREEZE,ST_SLEEP};

/* ── Items ──────────────────────────────────────────────────────── */
enum{IT_NONE,IT_LEFT,IT_CB,IT_LUM,IT_CHESTO,
     IT_SITRUS,IT_SALAC,IT_PETAYA,IT_LIECHI,
     IT_BRIGHTPOW,IT_SHELLBELL,IT_CSPEC,IT_WHITHERB};

/* ── Abilities ──────────────────────────────────────────────────── */
enum{AB_NONE,AB_KEEN,AB_LEVITATE,AB_THICKFAT,AB_STURDY,AB_CLEARBODY,
     AB_INTIMIDATE,AB_NATURALCURE,AB_SHEDSKIN};

/* ── Move effect IDs (agreed with Python EFFECT_MAP) ───────────── */
#define EF_NONE       0
#define EF_FLINCH     1
#define EF_BURN       2   /* secondary burn on damage */
#define EF_PARA       3   /* secondary paralysis on damage */
#define EF_FRZ        4   /* secondary freeze on damage */
#define EF_PSN        5   /* secondary poison on damage */
#define EF_SPDM       6   /* -1 SpD secondary */
#define EF_ATKP       7   /* +1 Atk self (Meteor Mash sec / Howl / Meditate) */
/* 8,9 reserved */
#define EF_TAUNT     10
#define EF_TOXIC     11
#define EF_CTR       12  /* Counter */
#define EF_SUB       13  /* Substitute */
#define EF_REST      14
#define EF_STALK     15  /* Sleep Talk */
#define EF_CURSE     16  /* non-Ghost Curse: +1 Atk +1 Def -1 Spe */
#define EF_TWAVE     17  /* Thunder Wave */
#define EF_WOW       18  /* Will-O-Wisp */
#define EF_PSPLIT    19  /* Pain Split */
#define EF_FPNCH     20  /* Focus Punch (interrupt if hit) */
#define EF_SLEEP_ST  21  /* sleep-inflicting status move */
#define EF_RECOVER   22  /* heal 50% max HP */
#define EF_ATK2P     23  /* +2 Atk (Swords Dance) */
#define EF_ATKSPE1P  24  /* +1 Atk +1 Spe (Dragon Dance) */
#define EF_CMIND     25  /* +1 SpA +1 SpD (Calm Mind) */
#define EF_AGIL      26  /* +2 Spe (Agility) */
#define EF_AMNESIA   27  /* +2 SpD */
#define EF_ALLP      28  /* +1 all stats (Ancient Power) */
#define EF_CONFUSE   29  /* secondary confuse (stub) */
#define EF_CONFUSE_ST 30 /* confuse-inflicting status move (stub) */
#define EF_OHKO      31  /* one-hit KO */
#define EF_SEISTOSS  32  /* fixed level-based damage */
#define EF_SPIKES    33  /* lay spikes (stub) */
#define EF_DEF2M     34  /* -2 Def opp (Screech) */
#define EF_SPE2M     35  /* -2 Spe opp (Scary Face) */
#define EF_SPD2M     36  /* -2 SpD opp (Metal Sound) */
#define EF_ATK1M     37  /* -1 Atk opp (Growl) */
#define EF_ATK2M     38  /* -2 Atk opp (Charm) */
#define EF_DEF1M     39  /* -1 Def opp (Leer) */
#define EF_SPE1M     40  /* -1 Spe secondary (Icy Wind, Rock Tomb) */
#define EF_DEF1P     41  /* +1 Def self secondary (Steel Wing) */
#define EF_SPA1M     42  /* -1 SpA secondary (Mist Ball) */
#define EF_SPA2M     43  /* -2 SpA self (Overheat) */
#define EF_ATKDEF1MS 44  /* -1 Atk -1 Def self (Superpower) */
#define EF_ATKDEF1MO 45  /* -1 Atk -1 Def opp (Tickle) */
#define EF_RAIN      46
#define EF_SUN       47
#define EF_HAIL      48
#define EF_SAND      49
#define EF_ROAR      50  /* phaze: stub */
#define EF_HAZE      51
#define EF_PSYCHUP   52
#define EF_SWAGGER   53  /* +2 Atk opp (confuse stub) */
#define EF_BELLYDRUM 54
#define EF_SPA3P     55  /* +3 SpA (Tail Glow) */
#define EF_BULKUP    56  /* +1 Atk +1 Def */
#define EF_COSMICPOW 57  /* +1 Def +1 SpD */
#define EF_ACIDARMOR 58  /* +2 Def */
#define EF_MIRRORCOAT 59
#define EF_LEECHSEED  60  /* stub */

/* ── Type chart ─────────────────────────────────────────────────── */
static float TC[NUM_T][NUM_T];
static int tc_done=0;
static void init_tc(void){
    if(tc_done)return;tc_done=1;
    for(int i=0;i<NUM_T;i++)for(int j=0;j<NUM_T;j++)TC[i][j]=1.0f;
    #define E(a,d,m) TC[a][d]=m
    E(T_NORMAL,T_ROCK,.5f);E(T_NORMAL,T_GHOST,0);E(T_NORMAL,T_STEEL,.5f);
    E(T_FIGHTING,T_NORMAL,2);E(T_FIGHTING,T_FLYING,.5f);E(T_FIGHTING,T_POISON,.5f);
    E(T_FIGHTING,T_ROCK,2);E(T_FIGHTING,T_BUG,.5f);E(T_FIGHTING,T_GHOST,0);
    E(T_FIGHTING,T_STEEL,2);E(T_FIGHTING,T_PSYCHIC,.5f);E(T_FIGHTING,T_ICE,2);
    E(T_FIGHTING,T_DARK,2);
    E(T_FLYING,T_FIGHTING,2);E(T_FLYING,T_ROCK,.5f);E(T_FLYING,T_BUG,2);
    E(T_FLYING,T_STEEL,.5f);E(T_FLYING,T_GRASS,2);E(T_FLYING,T_ELECTRIC,.5f);
    E(T_POISON,T_POISON,.5f);E(T_POISON,T_GROUND,.5f);E(T_POISON,T_ROCK,.5f);
    E(T_POISON,T_GHOST,.5f);E(T_POISON,T_STEEL,0);E(T_POISON,T_GRASS,2);
    E(T_GROUND,T_FLYING,0);E(T_GROUND,T_BUG,.5f);E(T_GROUND,T_STEEL,2);
    E(T_GROUND,T_FIRE,2);E(T_GROUND,T_GRASS,.5f);E(T_GROUND,T_ELECTRIC,2);
    E(T_GROUND,T_POISON,2);E(T_GROUND,T_ROCK,2);
    E(T_ROCK,T_FIGHTING,.5f);E(T_ROCK,T_GROUND,.5f);E(T_ROCK,T_STEEL,.5f);
    E(T_ROCK,T_FIRE,2);E(T_ROCK,T_FLYING,2);E(T_ROCK,T_BUG,2);E(T_ROCK,T_ICE,2);
    E(T_BUG,T_FIGHTING,.5f);E(T_BUG,T_FLYING,.5f);E(T_BUG,T_POISON,.5f);
    E(T_BUG,T_GHOST,.5f);E(T_BUG,T_STEEL,.5f);E(T_BUG,T_FIRE,.5f);
    E(T_BUG,T_GRASS,2);E(T_BUG,T_PSYCHIC,2);E(T_BUG,T_DARK,2);
    E(T_GHOST,T_NORMAL,0);E(T_GHOST,T_GHOST,2);E(T_GHOST,T_STEEL,.5f);
    E(T_GHOST,T_PSYCHIC,2);E(T_GHOST,T_DARK,.5f);
    E(T_STEEL,T_STEEL,.5f);E(T_STEEL,T_FIRE,.5f);E(T_STEEL,T_WATER,.5f);
    E(T_STEEL,T_ELECTRIC,.5f);E(T_STEEL,T_ROCK,2);E(T_STEEL,T_ICE,2);
    E(T_FIRE,T_ROCK,.5f);E(T_FIRE,T_BUG,2);E(T_FIRE,T_STEEL,2);
    E(T_FIRE,T_FIRE,.5f);E(T_FIRE,T_WATER,.5f);E(T_FIRE,T_GRASS,2);
    E(T_FIRE,T_ICE,2);E(T_FIRE,T_DRAGON,.5f);
    E(T_WATER,T_GROUND,2);E(T_WATER,T_ROCK,2);E(T_WATER,T_FIRE,2);
    E(T_WATER,T_WATER,.5f);E(T_WATER,T_GRASS,.5f);E(T_WATER,T_DRAGON,.5f);
    E(T_GRASS,T_FLYING,.5f);E(T_GRASS,T_POISON,.5f);E(T_GRASS,T_GROUND,2);
    E(T_GRASS,T_ROCK,2);E(T_GRASS,T_BUG,.5f);E(T_GRASS,T_STEEL,.5f);
    E(T_GRASS,T_FIRE,.5f);E(T_GRASS,T_WATER,2);E(T_GRASS,T_GRASS,.5f);
    E(T_GRASS,T_DRAGON,.5f);
    E(T_ELECTRIC,T_FLYING,2);E(T_ELECTRIC,T_GROUND,0);E(T_ELECTRIC,T_STEEL,.5f);
    E(T_ELECTRIC,T_WATER,2);E(T_ELECTRIC,T_GRASS,.5f);E(T_ELECTRIC,T_ELECTRIC,.5f);
    E(T_ELECTRIC,T_DRAGON,.5f);
    E(T_PSYCHIC,T_FIGHTING,2);E(T_PSYCHIC,T_POISON,2);E(T_PSYCHIC,T_STEEL,.5f);
    E(T_PSYCHIC,T_PSYCHIC,.5f);E(T_PSYCHIC,T_DARK,0);
    E(T_ICE,T_FLYING,2);E(T_ICE,T_GROUND,2);E(T_ICE,T_STEEL,.5f);
    E(T_ICE,T_FIRE,.5f);E(T_ICE,T_WATER,.5f);E(T_ICE,T_ICE,.5f);
    E(T_ICE,T_GRASS,2);E(T_ICE,T_DRAGON,2);
    E(T_DRAGON,T_STEEL,.5f);E(T_DRAGON,T_DRAGON,2);
    E(T_DARK,T_FIGHTING,.5f);E(T_DARK,T_GHOST,2);E(T_DARK,T_STEEL,.5f);
    E(T_DARK,T_PSYCHIC,2);E(T_DARK,T_DARK,.5f);
    #undef E
}

/* ── Move data (passed from Python) ────────────────────────────── */
typedef struct{int type,bp,acc,pri,eff,eff_ch,boom,brk;float recoil;}MV_t;
static MV_t *MV = NULL;
static int   NMV = 0;
static int   STRUGGLE_IDX = 0;

EXPORT void init_moves_data(MV_t *data, int count, int struggle_idx){
    MV = data;
    NMV = count;
    STRUGGLE_IDX = struggle_idx;
}

/* ── Stat stage tables ──────────────────────────────────────────── */
static const int SN[]={2,2,2,2,2,2,2,3,4,5,6,7,8};
static const int SD[]={8,7,6,5,4,3,2,2,2,2,2,2,2};
static int clamp(int v,int l,int h){return v<l?l:v>h?h:v;}
static int astg(int b,int s){int i=clamp(s,-6,6)+6;return b*SN[i]/SD[i];}
static int espd(int spe,int ss,int st){int s=astg(spe,ss);if(st==ST_PARA)s/=4;return s<1?1:s;}

/* ── PRNG (thread-local so OpenMP threads don't share state) ─────── */
static __thread unsigned rs=12345;
static int  ri(int n){rs^=rs<<13;rs^=rs>>17;rs^=rs<<5;return(int)(rs%(unsigned)n);}
static float rf(void){rs^=rs<<13;rs^=rs>>17;rs^=rs<<5;return(float)(rs&0x7FFFFFFF)/(float)0x80000000;}

/* ── Mon / State structs ─────────────────────────────────────────── */
typedef struct{
    int t1,t2,ab,item,item_c;
    int mv[4],mlock;
    int mhp,hp,atk,def,spa,spd,spe;
    int st,st_t;
    int as,ds,sas,sds,ss;     /* stat stages */
    int sub,taunt,flinch;
    int ldmg,lphys;           /* last damage taken, was physical? */
}Mon;

typedef struct{
    Mon team[2][3];
    int act[2];
    int weath,weath_t;
    int refl[2],ls[2],spk[2];
    int turn;
}State;

#define AM(s,p) ((s)->team[p][(s)->act[p]])

/* ── Berry / item checks ─────────────────────────────────────────── */
static void chk_berry(Mon*m){
    if(m->item==IT_LUM   &&!m->item_c&&m->st!=ST_NONE){m->st=ST_NONE;m->st_t=0;m->item_c=1;}
    if(m->item==IT_CHESTO&&!m->item_c&&m->st==ST_SLEEP){m->st=ST_NONE;m->st_t=0;m->item_c=1;}
}
/* Low-HP berries — called after each damage event */
static void chk_lohp_berry(Mon*m){
    if(m->hp<=0||m->item_c)return;
    if(m->item==IT_SITRUS&&m->hp<=m->mhp/2){
        int h=m->mhp/4;m->hp+=h;if(m->hp>m->mhp)m->hp=m->mhp;m->item_c=1;return;}
    if(m->item==IT_SALAC &&m->hp<=m->mhp/4){if(m->ss<6)m->ss++;m->item_c=1;return;}
    if(m->item==IT_PETAYA&&m->hp<=m->mhp/4){if(m->sas<6)m->sas++;m->item_c=1;return;}
    if(m->item==IT_LIECHI&&m->hp<=m->mhp/4){if(m->as<6)m->as++;m->item_c=1;return;}
}

/* ── Damage calculation ──────────────────────────────────────────── */
static int calc_dmg(Mon*a,Mon*d,MV_t*mv,int w,int crit,int refl,int ls){
    if(mv->bp==0)return 0;
    int mt=mv->type,ph=PHYS(mt),pw=mv->bp;
    if(d->ab==AB_THICKFAT&&(mt==T_FIRE||mt==T_ICE))pw/=2;
    if(!pw)return 0;
    int A,D_;
    if(ph){
        int s=crit&&a->as<0?0:a->as;
        A=astg(a->atk,s);
        if(a->item==IT_CB)A=A*3/2;
        if(a->st==ST_BURN)A/=2;
        int s2=crit&&d->ds>0?0:d->ds;
        D_=astg(d->def,s2);
        if(mv->boom)D_/=2;
        if(refl&&!crit&&!mv->brk)D_*=2;
    } else {
        int s=crit&&a->sas<0?0:a->sas;
        A=astg(a->spa,s);
        if(a->item==IT_CSPEC)A=A*3/2;
        int s2=crit&&d->sds>0?0:d->sds;
        D_=astg(d->spd,s2);
        if(ls&&!crit&&!mv->brk)D_*=2;
    }
    if(A<1)A=1;if(D_<1)D_=1;
    int base=(22*pw*A/D_)/50+2;
    /* weather */
    if(w==2&&mt==T_WATER)base=base*3/2;else if(w==2&&mt==T_FIRE)base/=2;
    else if(w==1&&mt==T_FIRE)base=base*3/2;else if(w==1&&mt==T_WATER)base/=2;
    if(crit)base*=2;
    /* STAB */
    if(mt==a->t1||mt==a->t2)base=base*3/2;
    /* immunity */
    if(d->ab==AB_LEVITATE&&mt==T_GROUND)return 0;
    float e1=TC[mt][d->t1];if(e1==0)return 0;
    if(e1==.5f)base/=2;else if(e1==2.f)base*=2;
    if(d->t2!=T_NONE&&d->t2!=d->t1){
        float e2=TC[mt][d->t2];if(e2==0)return 0;
        if(e2==.5f)base/=2;else if(e2==2.f)base*=2;
    }
    int roll=85+ri(16),dmg=base*roll/100;
    if(dmg<1&&base>0)dmg=1;
    return dmg;
}

/* ── Execute damage move ─────────────────────────────────────────── */
static int exec_dmg(State*s,int p,int mid){
    if(mid<0||mid>=NMV)return 0;
    MV_t*mv=&MV[mid];Mon*a=&AM(s,p);int o=1-p;Mon*d=&AM(s,o);
    if(mv->acc>0&&mv->acc<100&&ri(100)>=mv->acc)return 0;
    int crit=ri(16)==0;
    int dmg=calc_dmg(a,d,mv,s->weath,crit,s->refl[o],s->ls[o]);
    if(!dmg){if(mv->boom)a->hp=0;return 0;}
    int hit=0;
    if(d->sub>0){d->sub-=dmg;if(d->sub<0)d->sub=0;}
    else{d->hp-=dmg;if(d->hp<0)d->hp=0;d->ldmg=dmg;d->lphys=PHYS(mv->type);hit=1;}
    /* recoil / drain */
    if(mv->recoil>0){int r=(int)(dmg*mv->recoil);if(r<1)r=1;a->hp-=r;if(a->hp<0)a->hp=0;}
    else if(mv->recoil<0){int r=(int)(dmg*(-mv->recoil));if(r<1)r=1;a->hp+=r;if(a->hp>a->mhp)a->hp=a->mhp;}
    if(mv->boom)a->hp=0;
    /* Shell Bell */
    if(a->item==IT_SHELLBELL&&dmg>0){int h=dmg/8;if(h<1)h=1;a->hp+=h;if(a->hp>a->mhp)a->hp=a->mhp;}
    /* low-HP berries for both mon */
    chk_lohp_berry(d);chk_lohp_berry(a);
    /* secondary effects */
    if(mv->eff_ch>0&&hit&&d->hp>0&&d->sub==0&&ri(100)<mv->eff_ch){
        switch(mv->eff){
        case EF_BURN:
            if(!d->st&&d->t1!=T_FIRE&&d->t2!=T_FIRE){d->st=ST_BURN;chk_berry(d);}break;
        case EF_PARA:
            if(!d->st){d->st=ST_PARA;chk_berry(d);}break;
        case EF_FRZ:
            if(!d->st&&d->t1!=T_ICE&&d->t2!=T_ICE){d->st=ST_FREEZE;chk_berry(d);}break;
        case EF_PSN:
            if(!d->st&&d->t1!=T_POISON&&d->t2!=T_POISON&&
               d->t1!=T_STEEL&&d->t2!=T_STEEL){d->st=ST_POISON;chk_berry(d);}break;
        case EF_SPDM:
            if(d->ab!=AB_CLEARBODY&&d->sds>-6)d->sds--;break;
        case EF_ATKP:
            if(a->as<6)a->as++;break;
        case EF_SPE1M:
            if(d->ab!=AB_CLEARBODY&&d->ss>-6)d->ss--;break;
        case EF_DEF1P:
            if(a->ds<6)a->ds++;break;
        case EF_SPA1M:
            if(d->ab!=AB_CLEARBODY&&d->sas>-6)d->sas--;break;
        case EF_CONFUSE: break; /* stub */
        default:break;
        }
    }
    return hit;
}

/* ── Execute status/non-damage move ──────────────────────────────── */
static void exec_st(State*s,int p,int mid){
    if(mid<0||mid>=NMV)return;
    MV_t*mv=&MV[mid];Mon*a=&AM(s,p);int o=1-p;Mon*d=&AM(s,o);
    if(mv->acc>0&&mv->acc<100&&ri(100)>=mv->acc)return;
    switch(mv->eff){
    /* ── Original effects ── */
    case EF_TAUNT:  d->taunt=3;break;
    case EF_TOXIC:
        if(d->sub>0||d->st)break;
        if(d->t1==T_POISON||d->t2==T_POISON||d->t1==T_STEEL||d->t2==T_STEEL)break;
        d->st=ST_TOXIC;d->st_t=0;chk_berry(d);break;
    case EF_TWAVE:
        if(d->sub>0||d->st)break;
        if(d->t1==T_GROUND||d->t2==T_GROUND)break;
        d->st=ST_PARA;chk_berry(d);break;
    case EF_WOW:
        if(d->sub>0||d->st)break;
        if(d->t1==T_FIRE||d->t2==T_FIRE)break;
        d->st=ST_BURN;chk_berry(d);break;
    case EF_SUB:{
        int c=a->mhp/4;
        if(a->hp<=c||a->sub>0)break;
        a->hp-=c;a->sub=c;break;}
    case EF_REST:
        a->hp=a->mhp;a->st=ST_SLEEP;a->st_t=2;chk_berry(a);break;
    case EF_STALK:
        if(a->st!=ST_SLEEP)break;
        {int c[4],n=0;
         for(int i=0;i<4;i++)if(a->mv[i]!=mid&&a->mv[i]>=0&&a->mv[i]<NMV)c[n++]=a->mv[i];
         if(n>0){int ch=c[ri(n)];if(MV[ch].bp>0)exec_dmg(s,p,ch);else exec_st(s,p,ch);}}
        break;
    case EF_CURSE:
        if(a->as<6)a->as++;if(a->ds<6)a->ds++;if(a->ss>-6)a->ss--;break;
    case EF_PSPLIT:
        if(d->sub>0)break;
        {int avg=(a->hp+d->hp)/2;
         a->hp=avg<a->mhp?avg:a->mhp;
         d->hp=avg<d->mhp?avg:d->mhp;}break;
    case EF_CTR:
        if(!a->lphys||!a->ldmg)break;
        {int dm=a->ldmg*2;
         if(d->sub>0){d->sub-=dm;if(d->sub<0)d->sub=0;}
         else{d->hp-=dm;if(d->hp<0)d->hp=0;}}break;
    case EF_MIRRORCOAT:
        if(a->lphys||!a->ldmg)break;   /* only counters special damage */
        {int dm=a->ldmg*2;
         if(d->sub>0){d->sub-=dm;if(d->sub<0)d->sub=0;}
         else{d->hp-=dm;if(d->hp<0)d->hp=0;}}break;
    /* ── Self-boost ── */
    case EF_ATKP:   if(a->as<6)a->as++;break;
    case EF_ATK2P:  a->as+=2;if(a->as>6)a->as=6;break;
    case EF_ATKSPE1P: if(a->as<6)a->as++;if(a->ss<6)a->ss++;break;
    case EF_CMIND:  if(a->sas<6)a->sas++;if(a->sds<6)a->sds++;break;
    case EF_AGIL:   a->ss+=2;if(a->ss>6)a->ss=6;break;
    case EF_AMNESIA: a->sds+=2;if(a->sds>6)a->sds=6;break;
    case EF_BULKUP: if(a->as<6)a->as++;if(a->ds<6)a->ds++;break;
    case EF_COSMICPOW: if(a->ds<6)a->ds++;if(a->sds<6)a->sds++;break;
    case EF_ACIDARMOR: a->ds+=2;if(a->ds>6)a->ds=6;break;
    case EF_SPA3P:  a->sas+=3;if(a->sas>6)a->sas=6;break;
    case EF_ALLP:
        if(a->as<6)a->as++;if(a->ds<6)a->ds++;
        if(a->sas<6)a->sas++;if(a->sds<6)a->sds++;
        if(a->ss<6)a->ss++;break;
    case EF_BELLYDRUM:
        if(a->hp<=a->mhp/2)break;
        {int h=a->mhp/2;a->hp-=h;a->as=6;}break;
    /* ── Opponent stat drops ── */
    case EF_DEF2M:
        if(d->ab==AB_CLEARBODY)break;d->ds-=2;if(d->ds<-6)d->ds=-6;break;
    case EF_SPE2M:
        if(d->ab==AB_CLEARBODY)break;d->ss-=2;if(d->ss<-6)d->ss=-6;break;
    case EF_SPD2M:
        if(d->ab==AB_CLEARBODY)break;d->sds-=2;if(d->sds<-6)d->sds=-6;break;
    case EF_ATK1M:
        if(d->ab==AB_CLEARBODY)break;if(d->as>-6)d->as--;break;
    case EF_ATK2M:
        if(d->ab==AB_CLEARBODY)break;d->as-=2;if(d->as<-6)d->as=-6;break;
    case EF_DEF1M:
        if(d->ab==AB_CLEARBODY)break;if(d->ds>-6)d->ds--;break;
    case EF_ATKDEF1MO:
        if(d->ab==AB_CLEARBODY)break;
        if(d->as>-6)d->as--;if(d->ds>-6)d->ds--;break;
    /* ── Self stat drops ── */
    case EF_SPA2M:  a->sas-=2;if(a->sas<-6)a->sas=-6;break;
    case EF_ATKDEF1MS: a->as--;if(a->as<-6)a->as=-6;a->ds--;if(a->ds<-6)a->ds=-6;break;
    /* ── Recovery ── */
    case EF_RECOVER:{int h=a->mhp/2;a->hp+=h;if(a->hp>a->mhp)a->hp=a->mhp;}break;
    /* ── Status-inflicting ── */
    case EF_SLEEP_ST:
        if(d->sub>0||d->st)break;
        d->st=ST_SLEEP;d->st_t=2;chk_berry(d);break;
    /* ── Fixed damage ── */
    case EF_OHKO:
        if(d->ab==AB_STURDY||d->sub>0)break;
        d->hp=0;break;
    case EF_SEISTOSS:
        if(d->t1==T_GHOST||d->t2==T_GHOST)break;
        {int dm=50;  /* level 50 fixed damage */
         if(d->sub>0){d->sub-=dm;if(d->sub<0)d->sub=0;}
         else{d->hp-=dm;if(d->hp<0)d->hp=0;d->ldmg=dm;d->lphys=0;}}break;
    /* ── Weather ── */
    case EF_RAIN: s->weath=2;s->weath_t=5;break;
    case EF_SUN:  s->weath=1;s->weath_t=5;break;
    case EF_HAIL: s->weath=4;s->weath_t=5;break;
    case EF_SAND: s->weath=3;s->weath_t=5;break;
    /* ── Field effects ── */
    case EF_HAZE:
        a->as=a->ds=a->sas=a->sds=a->ss=0;
        d->as=d->ds=d->sas=d->sds=d->ss=0;break;
    case EF_PSYCHUP:
        a->as=d->as;a->ds=d->ds;a->sas=d->sas;a->sds=d->sds;a->ss=d->ss;break;
    case EF_SWAGGER:
        if(d->ab==AB_CLEARBODY)break;
        d->as+=2;if(d->as>6)d->as=6;break;  /* confuse stub */
    /* ── Stub / no-op ── */
    case EF_SPIKES: break;
    case EF_ROAR:   break;
    case EF_CONFUSE_ST: break;
    case EF_LEECHSEED: break;
    default: break;
    }
}

static int exec_mv(State*s,int p,int mid){
    if(mid<0||mid>=NMV)return 0;
    if(MV[mid].bp>0)return exec_dmg(s,p,mid);
    exec_st(s,p,mid);return 0;
}

/* ── Switch ──────────────────────────────────────────────────────── */
static void do_sw(State*s,int p,int idx){
    Mon*old=&AM(s,p);
    /* Natural Cure: cure status on switch-out */
    if(old->ab==AB_NATURALCURE)old->st=ST_NONE;
    old->as=old->ds=old->sas=old->sds=old->ss=0;
    old->sub=0;old->taunt=0;old->flinch=0;old->ldmg=0;old->lphys=0;old->mlock=-1;
    s->act[p]=idx;
    Mon*inc=&AM(s,p);
    /* Spikes */
    if(s->spk[p]>0&&inc->t1!=T_FLYING&&inc->t2!=T_FLYING&&inc->ab!=AB_LEVITATE){
        int d=inc->mhp/8;if(s->spk[p]==2)d=inc->mhp/6;else if(s->spk[p]>=3)d=inc->mhp/4;
        if(d<1)d=1;inc->hp-=d;if(inc->hp<0)inc->hp=0;
    }
    /* Intimidate: lower opponent's Atk by 1 */
    if(inc->ab==AB_INTIMIDATE){
        Mon*om=&AM(s,1-p);
        if(om->ab!=AB_CLEARBODY&&om->as>-6)om->as--;
    }
    chk_lohp_berry(inc);
}

/* ── End of turn ─────────────────────────────────────────────────── */
static void eot(State*s){
    for(int p=0;p<2;p++){
        Mon*m=&AM(s,p);
        if(m->hp<=0)continue;
        /* weather damage */
        if(s->weath==3){  /* sandstorm */
            if(m->t1!=T_ROCK&&m->t2!=T_ROCK&&m->t1!=T_GROUND&&m->t2!=T_GROUND&&
               m->t1!=T_STEEL&&m->t2!=T_STEEL){
                int d=m->mhp/16;if(d<1)d=1;m->hp-=d;if(m->hp<0)m->hp=0;
            }
        } else if(s->weath==4){  /* hail */
            if(m->t1!=T_ICE&&m->t2!=T_ICE){
                int d=m->mhp/16;if(d<1)d=1;m->hp-=d;if(m->hp<0)m->hp=0;
            }
        }
        /* Leftovers */
        if(m->item==IT_LEFT){int r=m->mhp/16;if(r<1)r=1;m->hp+=r;if(m->hp>m->mhp)m->hp=m->mhp;}
        /* burn/poison damage */
        if(m->st==ST_BURN){int d=m->mhp/8;if(d<1)d=1;m->hp-=d;}
        if(m->st==ST_POISON){int d=m->mhp/8;if(d<1)d=1;m->hp-=d;}
        if(m->st==ST_TOXIC){m->st_t++;int d=m->mhp*m->st_t/16;if(d<1)d=1;m->hp-=d;}
        if(m->hp<0)m->hp=0;
        /* Shed Skin */
        if(m->ab==AB_SHEDSKIN&&m->st!=ST_NONE&&ri(3)==0)m->st=ST_NONE;
        /* low-HP berries at EOT */
        chk_lohp_berry(m);
        /* misc reset */
        if(m->taunt>0)m->taunt--;
        m->flinch=0;m->ldmg=0;m->lphys=0;
    }
    /* weather countdown */
    if(s->weath_t>0){s->weath_t--;if(s->weath_t==0)s->weath=0;}
    s->turn++;
}

/* ── Terminal / bench helpers ────────────────────────────────────── */
typedef struct{int type,id;}Act;
static int abench(State*s,int p,int*out){
    int n=0;
    for(int i=0;i<3;i++)if(i!=s->act[p]&&s->team[p][i].hp>0)out[n++]=i;
    return n;
}
static int is_term(State*s){
    int a=0,b=0;
    for(int i=0;i<3;i++){if(s->team[0][i].hp>0)a=1;if(s->team[1][i].hp>0)b=1;}
    return!a||!b;
}
static int who_won(State*s){
    int a=0,b=0;
    for(int i=0;i<3;i++){if(s->team[0][i].hp>0)a=1;if(s->team[1][i].hp>0)b=1;}
    if(!b)return 0;if(!a)return 1;return-1;
}

/* ── Heuristic action selection for rollout AI ───────────────────── */
static Act choose_act(State*s,int p){
    if(!MV||!NMV)return(Act){0,STRUGGLE_IDX};
    Mon*m=&AM(s,p);int o=1-p;Mon*om=&AM(s,o);
    /* build legal move list */
    int lm[4],nm=0;
    for(int i=0;i<4;i++){
        int mid=m->mv[i];
        if(mid<0||mid>=NMV)continue;
        if(m->mlock>=0&&mid!=m->mlock)continue;
        if(m->taunt>0&&MV[mid].bp==0&&MV[mid].eff!=EF_CTR&&MV[mid].eff!=EF_MIRRORCOAT)continue;
        lm[nm++]=mid;
    }
    int bench[3],nb=abench(s,p,bench);
    float w[7];int at[7],ad[7],na=0;
    for(int i=0;i<nm;i++){
        MV_t*mv=&MV[lm[i]];
        at[na]=0;ad[na]=lm[i];
        if(mv->bp>0){
            /* damage weight: BP * type effectiveness */
            float eff=TC[mv->type][om->t1];
            if(om->t2!=T_NONE&&om->t2!=om->t1)eff*=TC[mv->type][om->t2];
            if(om->ab==AB_LEVITATE&&mv->type==T_GROUND)eff=0;
            float wt=mv->bp*eff/100.f;
            if(mv->type==m->t1||mv->type==m->t2)wt*=1.3f;
            w[na]=wt>.1f?wt:.1f;
        } else {
            int eff=mv->eff;
            /* status/utility weight heuristics */
            if(eff==EF_STALK)         w[na]=m->st==ST_SLEEP?3.f:.01f;
            else if(eff==EF_REST)     w[na]=m->hp<m->mhp/2?2.f:.2f;
            else if(eff==EF_RECOVER)  w[na]=m->hp<m->mhp/2?2.f:.2f;
            else if(eff==EF_CURSE)    w[na]=1.2f;
            else if(eff==EF_SUB)      w[na]=(m->sub>0||m->hp<=m->mhp/4)?.05f:1.f;
            else if(eff==EF_TOXIC||eff==EF_TWAVE||eff==EF_WOW||eff==EF_SLEEP_ST)
                                      w[na]=om->st?.05f:1.5f;
            /* setup moves */
            else if(eff==EF_ATK2P||eff==EF_ATKSPE1P||eff==EF_BULKUP)
                                      w[na]=(m->as<4&&m->hp>m->mhp/2)?1.5f:.15f;
            else if(eff==EF_CMIND||eff==EF_COSMICPOW)
                                      w[na]=(m->sas<4&&m->hp>m->mhp/2)?1.2f:.15f;
            else if(eff==EF_AGIL)     w[na]=m->ss<2?1.f:.1f;
            else if(eff==EF_AMNESIA||eff==EF_ACIDARMOR)
                                      w[na]=m->hp>m->mhp/2?1.0f:.1f;
            else if(eff==EF_SPA3P)    w[na]=(m->sas<4&&m->hp>m->mhp/2)?1.5f:.15f;
            else if(eff==EF_BELLYDRUM)w[na]=(m->as<6&&m->hp>m->mhp/2)?2.f:.01f;
            else if(eff==EF_ATKP)     w[na]=m->as<3?1.f:.1f;
            /* stat drops on opponent */
            else if(eff==EF_DEF2M||eff==EF_SPD2M)  w[na]=1.f;
            else if(eff==EF_ATK2M||eff==EF_SPE2M)  w[na]=.9f;
            else if(eff==EF_ATK1M||eff==EF_DEF1M)  w[na]=.7f;
            /* OHKO / fixed dmg */
            else if(eff==EF_OHKO)     w[na]=.6f;
            else if(eff==EF_SEISTOSS) w[na]=.6f;
            /* counter / mirror */
            else if(eff==EF_CTR)      w[na]=m->lphys&&m->ldmg?2.f:.1f;
            else if(eff==EF_MIRRORCOAT) w[na]=!m->lphys&&m->ldmg?2.f:.1f;
            /* weather */
            else if(eff==EF_RAIN||eff==EF_SUN||eff==EF_HAIL||eff==EF_SAND)
                                      w[na]=s->weath?.05f:.5f;
            else                      w[na]=.5f;
        }
        na++;
    }
    for(int i=0;i<nb;i++){at[na]=1;ad[na]=bench[i];w[na]=1.f;na++;}
    if(!na)return(Act){0,STRUGGLE_IDX};
    float sum=0;for(int i=0;i<na;i++)sum+=w[i];
    float r=rf()*sum,cum=0;
    for(int i=0;i<na;i++){cum+=w[i];if(r<=cum)return(Act){at[i],ad[i]};}
    return(Act){at[na-1],ad[na-1]};
}

/* ── Simulate one turn ───────────────────────────────────────────── */
static void sim_turn(State*s,Act a0,Act a1){
    int first=0;
    if(a0.type==1&&a1.type!=1)first=0;
    else if(a1.type==1&&a0.type!=1)first=1;
    else if(!a0.type&&!a1.type){
        if(MV&&a0.id<NMV&&a1.id<NMV){
            if(MV[a0.id].pri>MV[a1.id].pri)first=0;
            else if(MV[a1.id].pri>MV[a0.id].pri)first=1;
            else{int s0=espd(AM(s,0).spe,AM(s,0).ss,AM(s,0).st);
                 int s1=espd(AM(s,1).spe,AM(s,1).ss,AM(s,1).st);
                 first=s0>=s1?0:1;}
        }
    } else {
        int s0=espd(AM(s,0).spe,AM(s,0).ss,AM(s,0).st);
        int s1=espd(AM(s,1).spe,AM(s,1).ss,AM(s,1).st);
        first=s0>=s1?0:1;
    }
    int second=1-first;
    Act fa=first?a1:a0, sa=first?a0:a1;
    int hit2=0,acted=0;
    Mon*fm=&AM(s,first);
    if(fm->hp>0){
        if(fa.type==1){do_sw(s,first,fa.id);acted=1;}
        else{
            int mid=fa.id;
            int can=1;
            if(MV&&mid>=0&&mid<NMV&&fm->taunt>0&&
               MV[mid].bp==0&&MV[mid].eff!=EF_CTR&&MV[mid].eff!=EF_MIRRORCOAT)can=0;
            if(can&&fm->st==ST_SLEEP){
                if(fm->st_t>1){fm->st_t--;can=(MV&&mid<NMV&&MV[mid].eff==EF_STALK);}
                else{fm->st=ST_NONE;fm->st_t=0;}
            }
            if(can&&fm->st==ST_PARA&&ri(4)==0)can=0;
            if(can&&fm->st==ST_FREEZE){
                if(ri(5)==0){fm->st=ST_NONE;fm->st_t=0;}else can=0;
            }
            if(can){
                int oh=AM(s,second).hp;
                exec_mv(s,first,mid);
                hit2=AM(s,second).hp<oh;
                acted=1;
            }
        }
    }
    /* flinch */
    if(acted&&!fa.type&&MV&&fa.id<NMV&&MV[fa.id].eff==EF_FLINCH&&
       hit2&&AM(s,second).hp>0&&ri(100)<MV[fa.id].eff_ch)
        AM(s,second).flinch=1;
    /* second mon acts */
    Mon*sm=&AM(s,second);
    if(sm->hp>0&&!sm->flinch){
        if(sa.type==1)do_sw(s,second,sa.id);
        else{
            int mid=sa.id;
            int can=1;
            if(MV&&mid>=0&&mid<NMV&&sm->taunt>0&&
               MV[mid].bp==0&&MV[mid].eff!=EF_CTR&&MV[mid].eff!=EF_MIRRORCOAT)can=0;
            if(can&&MV&&mid>=0&&mid<NMV&&MV[mid].eff==EF_FPNCH&&hit2&&sm->sub==0)can=0;
            if(can&&sm->st==ST_SLEEP){
                if(sm->st_t>1){sm->st_t--;can=(MV&&mid<NMV&&MV[mid].eff==EF_STALK);}
                else{sm->st=ST_NONE;sm->st_t=0;}
            }
            if(can&&sm->st==ST_PARA&&ri(4)==0)can=0;
            if(can&&sm->st==ST_FREEZE){
                if(ri(5)==0){sm->st=ST_NONE;sm->st_t=0;}else can=0;
            }
            if(can)exec_mv(s,second,mid);
        }
    }
    eot(s);
    /* Choice Band/Specs lock */
    for(int pp=0;pp<2;pp++){
        Act act=pp==first?fa:sa;
        if(!act.type){
            Mon*mm=&AM(s,pp);
            if((mm->item==IT_CB||mm->item==IT_CSPEC)&&!mm->item_c&&mm->mlock<0&&mm->hp>0)
                mm->mlock=act.id;
        }
    }
}

/* ── Main rollout entry point ────────────────────────────────────── */
EXPORT int run_rollouts(State*init,int nsim,unsigned int seed){
    if(!MV||!NMV)return nsim/2;  /* not initialised: return 50% */
    init_tc();
    int wins=0;
#ifdef _OPENMP
    #pragma omp parallel reduction(+:wins)
    {
        /* Seed each thread's RNG independently from the master seed */
        rs = seed ^ ((unsigned)omp_get_thread_num() * 2654435761u);
        #pragma omp for schedule(static)
        for(int sim=0;sim<nsim;sim++){
#else
    rs=seed;
    for(int sim=0;sim<nsim;sim++){
#endif
            State s=*init;
            for(int t=0;t<80&&!is_term(&s);t++){
                /* forced switches for fainted mons */
                for(int pp=0;pp<2;pp++){
                    if(AM(&s,pp).hp<=0){
                        int ch[3],nc=abench(&s,pp,ch);
                        if(nc>0)do_sw(&s,pp,ch[ri(nc)]);
                    }
                }
                if(is_term(&s))break;
                Act a0=choose_act(&s,0),a1=choose_act(&s,1);
                sim_turn(&s,a0,a1);
            }
            if(who_won(&s)==0)wins++;
#ifdef _OPENMP
        }   /* end omp for */
    }       /* end omp parallel */
#else
    }
#endif
    return wins;
}
