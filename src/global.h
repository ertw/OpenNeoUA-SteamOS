#ifndef GLOBAL_H_INCLUDED
#define GLOBAL_H_INCLUDED

// Should be deleted


#ifdef GLOBAL

#define EXTR

#else

#define EXTR extern

#endif // GLOBAL

extern int dword_514EFC;
EXTR int dword_514F24;

EXTR TInputState input_states;
EXTR base_64arg world_update_arg;

EXTR NC_STACK_ypaworld *ypaworld;

enum GAME_SCREEN_MODE
{
    GAME_SCREEN_MODE_UNKNOWN = 0,
    GAME_SCREEN_MODE_MENU = 1,
    GAME_SCREEN_MODE_GAME = 2,
    GAME_SCREEN_MODE_REPLAY = 3
};

EXTR GAME_SCREEN_MODE GameScreenMode;


#endif // GLOBAL_H_INCLUDED1
