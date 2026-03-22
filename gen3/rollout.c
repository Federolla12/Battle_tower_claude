/*
 * Gen 3 Battle Engine - Fast Rollout Simulator (C Extension)
 * Compile:
 *   Linux:   gcc -O3 -shared -fPIC -o gen3/rollout.so gen3/rollout.c -lm
 *   Windows: gcc -O3 -shared -o gen3/rollout.dll gen3/rollout.c
 */
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
  #define EXPORT __declspec(dllexport)
#else
  #define EXPORT __attribute__((visibility("default")))
#endif

enum Type{T_NORMAL,T_FIGHTING,T_FLYING,T_POISON,T_GROUND,T_ROCK,T_BUG,T_GHOST,T_STEEL,T_FIRE,T_WATER,T_GRASS,T_ELECTRIC,T_PSYCHIC,T_ICE,T_DRAGON,T_DARK,T_NONE,T_UNK,NUM_T};
#define PHYS(t) ((t)<=T_STEEL)
enum{ST_NONE,ST_BURN,ST_PARA,ST_POISON,ST_TOXIC,ST_FREEZE,ST_SLEEP};
enum{IT_NONE,IT_LEFT,IT_CB,IT_LUM,IT_CHESTO};
enum{AB_NONE,AB_KEEN,AB_LEVITATE,AB_THICKFAT,AB_STURDY,AB_CLEARBODY};
enum{M_HP,M_TAUNT,M_COUNTER,M_TOXIC,M_GDRAIN,M_PSYCHIC,M_IPUNCH,M_FPUNCH,M_REST,M_STALK,M_CURSE,M_BSLAM,M_RSLIDE,M_SUB,M_FPNCH,M_TWAVE,M_WOW,M_FBLAST,M_SBOMB,M_PSPLIT,M_MMASH,M_EQ,M_BBREAK,M_BOOM,M_STRUGGLE,NUM_M};
#define EF_NONE 0
#define EF_FLINCH 1
#define EF_BURN 2
#define EF_PARA 3
#define EF_FRZ 4
#define EF_PSN 5
#define EF_SPDM 6
#define EF_ATKP 7
#define EF_TAUNT 10
#define EF_TOXIC 11
#define EF_CTR 12
#define EF_SUB 13
#define EF_REST 14
#define EF_STALK 15
#define EF_CURSE 16
#define EF_TWAVE 17
#define EF_WOW 18
#define EF_PSPLIT 19
#define EF_FPNCH 20

static float TC[NUM_T][NUM_T];
static int tc_done=0;
static void init_tc(void){
    if(tc_done)return;tc_done=1;
    for(int i=0;i<NUM_T;i++)for(int j=0;j<NUM_T;j++)TC[i][j]=1.0f;
    #define E(a,d,m) TC[a][d]=m
    E(T_NORMAL,T_ROCK,.5f);E(T_NORMAL,T_GHOST,0);E(T_NORMAL,T_STEEL,.5f);
    E(T_FIGHTING,T_NORMAL,2);E(T_FIGHTING,T_FLYING,.5f);E(T_FIGHTING,T_POISON,.5f);E(T_FIGHTING,T_ROCK,2);E(T_FIGHTING,T_BUG,.5f);E(T_FIGHTING,T_GHOST,0);E(T_FIGHTING,T_STEEL,2);E(T_FIGHTING,T_PSYCHIC,.5f);E(T_FIGHTING,T_ICE,2);E(T_FIGHTING,T_DARK,2);
    E(T_FLYING,T_FIGHTING,2);E(T_FLYING,T_ROCK,.5f);E(T_FLYING,T_BUG,2);E(T_FLYING,T_STEEL,.5f);E(T_FLYING,T_GRASS,2);E(T_FLYING,T_ELECTRIC,.5f);
    E(T_POISON,T_POISON,.5f);E(T_POISON,T_GROUND,.5f);E(T_POISON,T_ROCK,.5f);E(T_POISON,T_GHOST,.5f);E(T_POISON,T_STEEL,0);E(T_POISON,T_GRASS,2);
    E(T_GROUND,T_FLYING,0);E(T_GROUND,T_BUG,.5f);E(T_GROUND,T_STEEL,2);E(T_GROUND,T_FIRE,2);E(T_GROUND,T_GRASS,.5f);E(T_GROUND,T_ELECTRIC,2);E(T_GROUND,T_POISON,2);E(T_GROUND,T_ROCK,2);
    E(T_ROCK,T_FIGHTING,.5f);E(T_ROCK,T_GROUND,.5f);E(T_ROCK,T_STEEL,.5f);E(T_ROCK,T_FIRE,2);E(T_ROCK,T_FLYING,2);E(T_ROCK,T_BUG,2);E(T_ROCK,T_ICE,2);
    E(T_BUG,T_FIGHTING,.5f);E(T_BUG,T_FLYING,.5f);E(T_BUG,T_POISON,.5f);E(T_BUG,T_GHOST,.5f);E(T_BUG,T_STEEL,.5f);E(T_BUG,T_FIRE,.5f);E(T_BUG,T_GRASS,2);E(T_BUG,T_PSYCHIC,2);E(T_BUG,T_DARK,2);
    E(T_GHOST,T_NORMAL,0);E(T_GHOST,T_GHOST,2);E(T_GHOST,T_STEEL,.5f);E(T_GHOST,T_PSYCHIC,2);E(T_GHOST,T_DARK,.5f);
    E(T_STEEL,T_STEEL,.5f);E(T_STEEL,T_FIRE,.5f);E(T_STEEL,T_WATER,.5f);E(T_STEEL,T_ELECTRIC,.5f);E(T_STEEL,T_ROCK,2);E(T_STEEL,T_ICE,2);
    E(T_FIRE,T_ROCK,.5f);E(T_FIRE,T_BUG,2);E(T_FIRE,T_STEEL,2);E(T_FIRE,T_FIRE,.5f);E(T_FIRE,T_WATER,.5f);E(T_FIRE,T_GRASS,2);E(T_FIRE,T_ICE,2);E(T_FIRE,T_DRAGON,.5f);
    E(T_WATER,T_GROUND,2);E(T_WATER,T_ROCK,2);E(T_WATER,T_FIRE,2);E(T_WATER,T_WATER,.5f);E(T_WATER,T_GRASS,.5f);E(T_WATER,T_DRAGON,.5f);
    E(T_GRASS,T_FLYING,.5f);E(T_GRASS,T_POISON,.5f);E(T_GRASS,T_GROUND,2);E(T_GRASS,T_ROCK,2);E(T_GRASS,T_BUG,.5f);E(T_GRASS,T_STEEL,.5f);E(T_GRASS,T_FIRE,.5f);E(T_GRASS,T_WATER,2);E(T_GRASS,T_GRASS,.5f);E(T_GRASS,T_DRAGON,.5f);
    E(T_ELECTRIC,T_FLYING,2);E(T_ELECTRIC,T_GROUND,0);E(T_ELECTRIC,T_STEEL,.5f);E(T_ELECTRIC,T_WATER,2);E(T_ELECTRIC,T_GRASS,.5f);E(T_ELECTRIC,T_ELECTRIC,.5f);E(T_ELECTRIC,T_DRAGON,.5f);
    E(T_PSYCHIC,T_FIGHTING,2);E(T_PSYCHIC,T_POISON,2);E(T_PSYCHIC,T_STEEL,.5f);E(T_PSYCHIC,T_PSYCHIC,.5f);E(T_PSYCHIC,T_DARK,0);
    E(T_ICE,T_FLYING,2);E(T_ICE,T_GROUND,2);E(T_ICE,T_STEEL,.5f);E(T_ICE,T_FIRE,.5f);E(T_ICE,T_WATER,.5f);E(T_ICE,T_ICE,.5f);E(T_ICE,T_GRASS,2);E(T_ICE,T_DRAGON,2);
    E(T_DRAGON,T_STEEL,.5f);E(T_DRAGON,T_DRAGON,2);
    E(T_DARK,T_FIGHTING,.5f);E(T_DARK,T_GHOST,2);E(T_DARK,T_STEEL,.5f);E(T_DARK,T_PSYCHIC,2);E(T_DARK,T_DARK,.5f);
    #undef E
}

typedef struct{int type,bp,acc,pri,eff,eff_ch,boom,brk;float recoil;}MV_t;
static MV_t MV[NUM_M];
static void init_mv(void){
    memset(MV,0,sizeof(MV));
    #define D(id,t,b,a,p,e,ec,bo,br,rc) MV[id]=(MV_t){t,b,a,p,e,ec,bo,br,rc}
    D(M_HP,T_GROUND,70,100,0,0,0,0,0,0);D(M_TAUNT,T_DARK,0,100,0,EF_TAUNT,100,0,0,0);D(M_COUNTER,T_FIGHTING,0,100,-5,EF_CTR,100,0,0,0);D(M_TOXIC,T_POISON,0,85,0,EF_TOXIC,100,0,0,0);
    D(M_GDRAIN,T_GRASS,60,100,0,0,0,0,0,-.5f);D(M_PSYCHIC,T_PSYCHIC,90,100,0,EF_SPDM,10,0,0,0);D(M_IPUNCH,T_ICE,75,100,0,EF_FRZ,10,0,0,0);D(M_FPUNCH,T_FIRE,75,100,0,EF_BURN,10,0,0,0);
    D(M_REST,T_PSYCHIC,0,0,0,EF_REST,100,0,0,0);D(M_STALK,T_NORMAL,0,0,0,EF_STALK,100,0,0,0);D(M_CURSE,T_UNK,0,0,0,EF_CURSE,100,0,0,0);D(M_BSLAM,T_NORMAL,85,100,0,EF_PARA,30,0,0,0);
    D(M_RSLIDE,T_ROCK,75,90,0,EF_FLINCH,30,0,0,0);D(M_SUB,T_NORMAL,0,0,0,EF_SUB,100,0,0,0);D(M_FPNCH,T_FIGHTING,150,100,-3,EF_FPNCH,100,0,0,0);D(M_TWAVE,T_ELECTRIC,0,100,0,EF_TWAVE,100,0,0,0);
    D(M_WOW,T_FIRE,0,75,0,EF_WOW,100,0,0,0);D(M_FBLAST,T_FIRE,120,85,0,EF_BURN,10,0,0,0);D(M_SBOMB,T_POISON,90,100,0,EF_PSN,30,0,0,0);D(M_PSPLIT,T_NORMAL,0,0,0,EF_PSPLIT,100,0,0,0);
    D(M_MMASH,T_STEEL,100,85,0,EF_ATKP,20,0,0,0);D(M_EQ,T_GROUND,100,100,0,0,0,0,0,0);D(M_BBREAK,T_FIGHTING,75,100,0,0,0,0,1,0);D(M_BOOM,T_NORMAL,250,100,0,0,0,1,0,0);
    D(M_STRUGGLE,T_NORMAL,50,100,0,0,0,0,0,.25f);
    #undef D
}

typedef struct{int t1,t2,ab,item,item_c;int mv[4],mlock;int mhp,hp,atk,def,spa,spd,spe;int st,st_t;int as,ds,sas,sds,ss;int sub,taunt,flinch,ldmg,lphys;}Mon;
typedef struct{Mon team[2][3];int act[2];int weath,weath_t,refl[2],ls[2],spk[2],turn;}State;
#define AM(s,p) ((s)->team[p][(s)->act[p]])

static const int SN[]={2,2,2,2,2,2,2,3,4,5,6,7,8},SD[]={8,7,6,5,4,3,2,2,2,2,2,2,2};
static int clamp(int v,int l,int h){return v<l?l:v>h?h:v;}
static int astg(int b,int s){int i=clamp(s,-6,6)+6;return b*SN[i]/SD[i];}
static int espd(Mon*m){int s=astg(m->spe,m->ss);if(m->st==ST_PARA)s/=4;return s<1?1:s;}

static unsigned rs=12345;
static int ri(int n){rs^=rs<<13;rs^=rs>>17;rs^=rs<<5;return(int)(rs%(unsigned)n);}
static float rf(void){rs^=rs<<13;rs^=rs>>17;rs^=rs<<5;return(float)(rs&0x7FFFFFFF)/(float)0x80000000;}

static void chk_berry(Mon*m){
    if(m->item==IT_LUM&&!m->item_c&&m->st!=ST_NONE){m->st=ST_NONE;m->st_t=0;m->item_c=1;}
    if(m->item==IT_CHESTO&&!m->item_c&&m->st==ST_SLEEP){m->st=ST_NONE;m->st_t=0;m->item_c=1;}
}

static int calc_dmg(Mon*a,Mon*d,MV_t*mv,int w,int crit,int refl,int ls){
    if(mv->bp==0)return 0;
    int mt=mv->type,ph=PHYS(mt),pw=mv->bp;
    if(d->ab==AB_THICKFAT&&(mt==T_FIRE||mt==T_ICE))pw/=2;
    if(!pw)return 0;
    int A,D_;
    if(ph){int s=crit&&a->as<0?0:a->as;A=astg(a->atk,s);if(a->item==IT_CB)A=A*3/2;if(a->st==ST_BURN)A/=2;
           int s2=crit&&d->ds>0?0:d->ds;D_=astg(d->def,s2);if(mv->boom)D_/=2;if(refl&&!crit&&!mv->brk)D_*=2;}
    else{int s=crit&&a->sas<0?0:a->sas;A=astg(a->spa,s);int s2=crit&&d->sds>0?0:d->sds;D_=astg(d->spd,s2);if(ls&&!crit&&!mv->brk)D_*=2;}
    if(A<1)A=1;if(D_<1)D_=1;
    int base=(22*pw*A/D_)/50+2;
    if(w==2&&mt==T_WATER)base=base*3/2;else if(w==2&&mt==T_FIRE)base/=2;
    else if(w==1&&mt==T_FIRE)base=base*3/2;else if(w==1&&mt==T_WATER)base/=2;
    if(crit)base*=2;
    if(mt==a->t1||mt==a->t2)base=base*3/2;
    if(d->ab==AB_LEVITATE&&mt==T_GROUND)return 0;
    float e1=TC[mt][d->t1];if(e1==0)return 0;if(e1==.5f)base/=2;else if(e1==2.f)base*=2;
    if(d->t2!=T_NONE&&d->t2!=d->t1){float e2=TC[mt][d->t2];if(e2==0)return 0;if(e2==.5f)base/=2;else if(e2==2.f)base*=2;}
    int roll=85+ri(16),dmg=base*roll/100;if(dmg<1&&base>0)dmg=1;return dmg;
}

static int exec_dmg(State*s,int p,int mid){
    MV_t*mv=&MV[mid];Mon*a=&AM(s,p);int o=1-p;Mon*d=&AM(s,o);
    if(mv->acc>0&&mv->acc<100&&ri(100)>=mv->acc)return 0;
    int crit=ri(16)==0,dmg=calc_dmg(a,d,mv,s->weath,crit,s->refl[o],s->ls[o]);
    if(!dmg){if(mv->boom)a->hp=0;return 0;}
    int hit=0;
    if(d->sub>0){d->sub-=dmg;if(d->sub<0)d->sub=0;}
    else{d->hp-=dmg;if(d->hp<0)d->hp=0;d->ldmg=dmg;d->lphys=PHYS(mv->type);hit=1;}
    if(mv->recoil>0){int r=(int)(dmg*mv->recoil);if(r<1)r=1;a->hp-=r;if(a->hp<0)a->hp=0;}
    else if(mv->recoil<0){int r=(int)(dmg*(-mv->recoil));if(r<1)r=1;a->hp+=r;if(a->hp>a->mhp)a->hp=a->mhp;}
    if(mv->boom)a->hp=0;
    if(mv->eff_ch>0&&hit&&d->hp>0&&d->sub==0&&ri(100)<mv->eff_ch){
        switch(mv->eff){
        case EF_BURN:if(!d->st&&d->t1!=T_FIRE&&d->t2!=T_FIRE){d->st=ST_BURN;chk_berry(d);}break;
        case EF_PARA:if(!d->st){d->st=ST_PARA;chk_berry(d);}break;
        case EF_FRZ:if(!d->st&&d->t1!=T_ICE&&d->t2!=T_ICE){d->st=ST_FREEZE;chk_berry(d);}break;
        case EF_PSN:if(!d->st&&d->t1!=T_POISON&&d->t2!=T_POISON&&d->t1!=T_STEEL&&d->t2!=T_STEEL){d->st=ST_POISON;chk_berry(d);}break;
        case EF_SPDM:if(d->ab!=AB_CLEARBODY&&d->sds>-6)d->sds--;break;
        case EF_ATKP:if(a->as<6)a->as++;break;
        default:break;}
    }
    return hit;
}

static void exec_st(State*s,int p,int mid){
    MV_t*mv=&MV[mid];Mon*a=&AM(s,p);int o=1-p;Mon*d=&AM(s,o);
    if(mv->acc>0&&mv->acc<100&&ri(100)>=mv->acc)return;
    switch(mv->eff){
    case EF_TAUNT:d->taunt=2;break;
    case EF_TOXIC:if(d->sub>0||d->st)break;if(d->t1==T_POISON||d->t2==T_POISON||d->t1==T_STEEL||d->t2==T_STEEL)break;d->st=ST_TOXIC;d->st_t=0;chk_berry(d);break;
    case EF_TWAVE:if(d->sub>0||d->st)break;if(d->t1==T_GROUND||d->t2==T_GROUND)break;d->st=ST_PARA;chk_berry(d);break;
    case EF_WOW:if(d->sub>0||d->st)break;if(d->t1==T_FIRE||d->t2==T_FIRE)break;d->st=ST_BURN;chk_berry(d);break;
    case EF_SUB:{int c=a->mhp/4;if(a->hp<=c||a->sub>0)break;a->hp-=c;a->sub=c;}break;
    case EF_REST:a->hp=a->mhp;a->st=ST_SLEEP;a->st_t=2;chk_berry(a);break;
    case EF_STALK:if(a->st!=ST_SLEEP)break;{int c[4],n=0;for(int i=0;i<4;i++)if(a->mv[i]!=M_STALK)c[n++]=a->mv[i];if(n>0){int ch=c[ri(n)];if(MV[ch].bp>0)exec_dmg(s,p,ch);else exec_st(s,p,ch);}}break;
    case EF_CURSE:if(a->as<6)a->as++;if(a->ds<6)a->ds++;if(a->ss>-6)a->ss--;break;
    case EF_PSPLIT:if(d->sub>0)break;{int avg=(a->hp+d->hp)/2;a->hp=avg<a->mhp?avg:a->mhp;d->hp=avg<d->mhp?avg:d->mhp;}break;
    case EF_CTR:if(!a->lphys||!a->ldmg)break;{int dm=a->ldmg*2;if(d->sub>0){d->sub-=dm;if(d->sub<0)d->sub=0;}else{d->hp-=dm;if(d->hp<0)d->hp=0;}}break;
    default:break;}
}

static int exec_mv(State*s,int p,int mid){if(MV[mid].bp>0)return exec_dmg(s,p,mid);exec_st(s,p,mid);return 0;}

static void do_sw(State*s,int p,int idx){
    Mon*old=&AM(s,p);old->as=old->ds=old->sas=old->sds=old->ss=0;old->sub=0;old->taunt=0;old->flinch=0;old->ldmg=0;old->lphys=0;old->mlock=-1;
    s->act[p]=idx;Mon*inc=&AM(s,p);
    if(s->spk[p]>0&&inc->t1!=T_FLYING&&inc->t2!=T_FLYING&&inc->ab!=AB_LEVITATE){int d;if(s->spk[p]==1)d=inc->mhp/8;else if(s->spk[p]==2)d=inc->mhp/6;else d=inc->mhp/4;if(d<1)d=1;inc->hp-=d;if(inc->hp<0)inc->hp=0;}
}

static void eot(State*s){
    for(int p=0;p<2;p++){Mon*m=&AM(s,p);if(m->hp<=0)continue;
        if(s->weath==3&&m->t1!=T_ROCK&&m->t2!=T_ROCK&&m->t1!=T_GROUND&&m->t2!=T_GROUND&&m->t1!=T_STEEL&&m->t2!=T_STEEL){int d=m->mhp/16;if(d<1)d=1;m->hp-=d;}
        if(m->item==IT_LEFT){int r=m->mhp/16;if(r<1)r=1;m->hp+=r;if(m->hp>m->mhp)m->hp=m->mhp;}
        if(m->st==ST_BURN){int d=m->mhp/8;if(d<1)d=1;m->hp-=d;}
        if(m->st==ST_POISON){int d=m->mhp/8;if(d<1)d=1;m->hp-=d;}
        if(m->st==ST_TOXIC){m->st_t++;int d=m->mhp*m->st_t/16;if(d<1)d=1;m->hp-=d;}
        if(m->hp<0)m->hp=0;if(m->taunt>0)m->taunt--;m->flinch=0;m->ldmg=0;m->lphys=0;}
    s->turn++;
}

typedef struct{int type,id;}Act;
static int abench(State*s,int p,int*out){int n=0;for(int i=0;i<3;i++)if(i!=s->act[p]&&s->team[p][i].hp>0)out[n++]=i;return n;}
static int is_term(State*s){int a=0,b=0;for(int i=0;i<3;i++){if(s->team[0][i].hp>0)a=1;if(s->team[1][i].hp>0)b=1;}return!a||!b;}
static int who_won(State*s){int a=0,b=0;for(int i=0;i<3;i++){if(s->team[0][i].hp>0)a=1;if(s->team[1][i].hp>0)b=1;}if(!b)return 0;if(!a)return 1;return-1;}

static Act choose_act(State*s,int p){
    Mon*m=&AM(s,p);int o=1-p;Mon*om=&AM(s,o);
    int lm[4],nm=0;for(int i=0;i<4;i++){int mid=m->mv[i];if(m->mlock>=0&&mid!=m->mlock)continue;if(m->taunt>0&&MV[mid].bp==0&&MV[mid].eff!=EF_CTR)continue;lm[nm++]=mid;}
    int bench[2],nb=abench(s,p,bench);
    float w[6];int at[6],ad[6],na=0;
    for(int i=0;i<nm;i++){MV_t*mv=&MV[lm[i]];at[na]=0;ad[na]=lm[i];
        if(mv->bp>0){float eff=TC[mv->type][om->t1];if(om->t2!=T_NONE&&om->t2!=om->t1)eff*=TC[mv->type][om->t2];if(om->ab==AB_LEVITATE&&mv->type==T_GROUND)eff=0;float wt=mv->bp*eff/100.f;if(mv->type==m->t1||mv->type==m->t2)wt*=1.3f;w[na]=wt>.1f?wt:.1f;}
        else{if(mv->eff==EF_STALK)w[na]=m->st==ST_SLEEP?3.f:.01f;else if(mv->eff==EF_REST)w[na]=m->hp<m->mhp/2?2.f:.2f;else if(mv->eff==EF_CURSE)w[na]=1.2f;else if(mv->eff==EF_SUB)w[na]=(m->sub>0||m->hp<=m->mhp/4)?.05f:1.f;else if(mv->eff==EF_TOXIC||mv->eff==EF_TWAVE||mv->eff==EF_WOW)w[na]=om->st?.05f:1.5f;else w[na]=.8f;}
        na++;}
    for(int i=0;i<nb;i++){at[na]=1;ad[na]=bench[i];w[na]=1.f;na++;}
    if(!na)return(Act){0,M_STRUGGLE};
    float sum=0;for(int i=0;i<na;i++)sum+=w[i];float r=rf()*sum,cum=0;
    for(int i=0;i<na;i++){cum+=w[i];if(r<=cum)return(Act){at[i],ad[i]};}
    return(Act){at[na-1],ad[na-1]};
}

static void sim_turn(State*s,Act a0,Act a1){
    int first=0;
    if(a0.type==1&&a1.type!=1)first=0;else if(a1.type==1&&a0.type!=1)first=1;
    else if(!a0.type&&!a1.type){if(MV[a0.id].pri>MV[a1.id].pri)first=0;else if(MV[a1.id].pri>MV[a0.id].pri)first=1;else{int s0=espd(&AM(s,0)),s1=espd(&AM(s,1));first=s0>=s1?0:1;}}
    else{int s0=espd(&AM(s,0)),s1=espd(&AM(s,1));first=s0>=s1?0:1;}
    int second=1-first;Act fa=first?a1:a0,sa=first?a0:a1;
    int hit2=0,acted=0;
    Mon*fm=&AM(s,first);
    if(fm->hp>0){if(fa.type==1){do_sw(s,first,fa.id);acted=1;}else{
        MV_t*fmv=&MV[fa.id];int can=1;
        if(fm->taunt>0&&fmv->bp==0&&fmv->eff!=EF_CTR)can=0;
        if(can&&fm->st==ST_SLEEP){if(fm->st_t>1){fm->st_t--;can=fa.id==M_STALK;}else{fm->st=ST_NONE;fm->st_t=0;}}
        if(can&&fm->st==ST_PARA&&ri(4)==0)can=0;
        if(can&&fm->st==ST_FREEZE){if(ri(5)==0){fm->st=ST_NONE;fm->st_t=0;}else can=0;}
        if(can){int oh=AM(s,second).hp;exec_mv(s,first,fa.id);hit2=AM(s,second).hp<oh;acted=1;}}}
    if(acted&&!fa.type&&MV[fa.id].eff==EF_FLINCH&&hit2&&AM(s,second).hp>0&&ri(100)<MV[fa.id].eff_ch)AM(s,second).flinch=1;
    Mon*sm=&AM(s,second);
    if(sm->hp>0&&!sm->flinch){if(sa.type==1)do_sw(s,second,sa.id);else{
        MV_t*smv=&MV[sa.id];int can=1;
        if(sm->taunt>0&&smv->bp==0&&smv->eff!=EF_CTR)can=0;
        if(can&&smv->eff==EF_FPNCH&&hit2&&sm->sub==0)can=0;
        if(can&&sm->st==ST_SLEEP){if(sm->st_t>1){sm->st_t--;can=sa.id==M_STALK;}else{sm->st=ST_NONE;sm->st_t=0;}}
        if(can&&sm->st==ST_PARA&&ri(4)==0)can=0;
        if(can&&sm->st==ST_FREEZE){if(ri(5)==0){sm->st=ST_NONE;sm->st_t=0;}else can=0;}
        if(can)exec_mv(s,second,sa.id);}}
    eot(s);
    for(int p=0;p<2;p++){Act act=p==first?fa:sa;if(!act.type){Mon*m=&AM(s,p);if(m->item==IT_CB&&!m->item_c&&m->mlock<0&&m->hp>0)m->mlock=act.id;}}
}

EXPORT int run_rollouts(State*init,int nsim,unsigned int seed){
    init_tc();init_mv();rs=seed;int wins=0;
    for(int sim=0;sim<nsim;sim++){
        State s=*init;
        for(int t=0;t<80&&!is_term(&s);t++){
            for(int p=0;p<2;p++){if(AM(&s,p).hp<=0){int ch[3],nc=abench(&s,p,ch);if(nc>0)do_sw(&s,p,ch[ri(nc)]);}}
            if(is_term(&s))break;
            Act a0=choose_act(&s,0),a1=choose_act(&s,1);sim_turn(&s,a0,a1);}
        if(who_won(&s)==0)wins++;}
    return wins;
}
